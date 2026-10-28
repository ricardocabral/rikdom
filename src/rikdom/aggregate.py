from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeGuard
from datetime import date, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

from .activities import check_financial_contract, effective_activities

from rikdom.reconciliation import (
    Finding,
    FxSource,
    HoldingTrustRecord,
    Severity,
    record_finding,
)


@dataclass
class AggregateResult:
    base_currency: str
    total_value_base: float
    by_asset_class: dict[str, float]
    warnings: list[str]
    errors: list[str] = field(default_factory=list)
    fx_lock: dict[str, Any] | None = None
    by_region: dict[str, float] = field(default_factory=dict)
    by_currency: dict[str, float] = field(default_factory=dict)
    by_duration: dict[str, float] = field(default_factory=dict)
    by_liquidity_tier: dict[str, float] = field(default_factory=dict)
    by_account: dict[str, float] = field(default_factory=dict)
    by_strategic_bucket: dict[str, float] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    trust_records: list[HoldingTrustRecord] = field(default_factory=list)
    quantity_reconciliation: list[dict[str, Any]] = field(default_factory=list)
    import_diagnostics: dict[str, Any] = field(default_factory=dict)


UNCLASSIFIED = "__unclassified__"
UNASSIGNED_ACCOUNT = "__unassigned__"
UNALLOCATED_BUCKET = "__unallocated__"
_LOOKTHROUGH_DIMENSIONS = ("region", "currency", "duration", "liquidity_tier")
_STRATEGIC_DIMENSIONS = (
    "asset_class",
    "region",
    "currency",
    "duration",
    "liquidity_tier",
)


def strategic_bucket_key(dimension: str, bucket: str) -> str:
    """Stable composite key for a policy strategic_allocation target."""

    return f"{dimension}:{bucket}"


def compute_strategic_bucket_totals(
    aggregate: "AggregateResult", policy: dict[str, Any] | None
) -> dict[str, float]:
    """Reduce per-dimension aggregate breakdowns to the policy's targets.

    Returns a flat map keyed by ``"<dimension>:<bucket>"`` plus an
    ``__unallocated__`` entry for portfolio value not covered by any
    target. Dimensions outside the supported set
    (asset_class/region/currency/duration/liquidity_tier) are skipped.
    """

    if not isinstance(policy, dict):
        return {}
    strat = policy.get("strategic_allocation")
    if not isinstance(strat, dict):
        return {}
    targets = strat.get("targets") or []

    dim_breakdowns: dict[str, dict[str, float]] = {
        "asset_class": aggregate.by_asset_class,
        "region": aggregate.by_region,
        "currency": aggregate.by_currency,
        "duration": aggregate.by_duration,
        "liquidity_tier": aggregate.by_liquidity_tier,
    }

    out: dict[str, float] = {}
    allocated_by_dim: dict[str, float] = {}
    seen_dims: set[str] = set()
    for tgt in targets:
        if not isinstance(tgt, dict):
            continue
        dim = tgt.get("dimension")
        bucket = tgt.get("bucket")
        if not isinstance(dim, str) or dim not in _STRATEGIC_DIMENSIONS:
            continue
        if not isinstance(bucket, str) or not bucket:
            continue
        breakdown = dim_breakdowns.get(dim) or {}
        value = breakdown.get(bucket, 0.0)
        out[strategic_bucket_key(dim, bucket)] = float(value)
        allocated_by_dim[dim] = allocated_by_dim.get(dim, 0.0) + float(value)
        seen_dims.add(dim)

    # __unallocated__ uses the breakdown of the dominant dimension to
    # avoid double-counting when multiple dimensions are targeted.
    if seen_dims:
        dominant = max(
            seen_dims,
            key=lambda d: sum((dim_breakdowns.get(d) or {}).values()),
        )
        total_in_dim = sum((dim_breakdowns.get(dominant) or {}).values())
        leftover = total_in_dim - allocated_by_dim.get(dominant, 0.0)
        if abs(leftover) > 0.005:
            out[UNALLOCATED_BUCKET] = leftover
    return out


_IDENTIFIER_FIELDS = ("isin", "ticker", "wallet", "provider_account_id", "id")
_HIGH_CONFIDENCE_IDENTIFIER_FIELDS = ("isin", "ticker", "id")
_LOW_CONFIDENCE_IDENTIFIER_FIELDS = ("provider_account_id", "wallet")
_HIGH_CONFIDENCE_IDENTIFIER_FIELDS_SET = set(_HIGH_CONFIDENCE_IDENTIFIER_FIELDS)

_QUANTITY_EVENT_SIGNS: dict[str, float] = {
    "buy": 1.0,
    "sell": -1.0,
    "transfer_in": 1.0,
    "transfer_out": -1.0,
    "split": 1.0,
}

_CASH_EVENT_SIGNS: dict[str, float] = {
    "buy": -1.0,
    "sell": 1.0,
    "dividend": 1.0,
    "interest": 1.0,
    "fee": -1.0,
    "transfer_in": 1.0,
    "transfer_out": -1.0,
    "income": 1.0,
    "reimbursement": 1.0,
}


def _is_numeric(value: Any) -> TypeGuard[int | float]:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _catalog_exposure_index(
    asset_type_catalog: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in asset_type_catalog:
        type_id = str(item.get("id", "")).strip()
        exposure = item.get("economic_exposure")
        if type_id and isinstance(exposure, dict):
            index[type_id] = exposure
    return index


def _resolve_holding_exposure(
    holding: dict[str, Any],
    asset_type_id: str,
    catalog_exposures: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    holding_exposure = holding.get("economic_exposure")
    if isinstance(holding_exposure, dict):
        return holding_exposure
    catalog_exposure = catalog_exposures.get(asset_type_id)
    if isinstance(catalog_exposure, dict):
        return catalog_exposure
    return None


def _holding_market_value_currency(holding: dict[str, Any]) -> str | None:
    mv = holding.get("market_value")
    if not isinstance(mv, dict):
        return None
    cur = mv.get("currency")
    if isinstance(cur, str) and len(cur.strip()) == 3:
        return cur.strip().upper()
    return None


def _lookthrough_bucket(dim: str, line: dict[str, Any], holding: dict[str, Any]) -> str:
    value = line.get(dim)
    if isinstance(value, str) and value.strip():
        return value.strip().upper() if dim == "currency" else value.strip()
    if dim == "currency":
        return _holding_market_value_currency(holding) or UNCLASSIFIED
    return UNCLASSIFIED


def _distribute_unclassified_lookthrough(
    breakdowns: dict[str, dict[str, float]],
    holding: dict[str, Any],
    amount_base: float,
) -> None:
    for dim in _LOOKTHROUGH_DIMENSIONS:
        bucket = _holding_market_value_currency(holding) if dim == "currency" else None
        bucket = bucket or UNCLASSIFIED
        breakdowns[dim][bucket] = breakdowns[dim].get(bucket, 0.0) + amount_base


def _distribute_lookthrough(
    breakdowns: dict[str, dict[str, float]],
    exposure: dict[str, Any] | None,
    holding: dict[str, Any],
    amount_base: float,
    warnings: list[str] | None = None,
    findings: list[Finding] | None = None,
) -> None:
    """Apportion amount_base across by_region/by_currency/by_duration/by_liquidity_tier buckets.

    Precedence: holding.economic_exposure -> asset_type.economic_exposure ->
    (currency only) holding.market_value.currency. Anything else lands in __unclassified__.
    """

    if exposure is None or not isinstance(exposure.get("breakdown"), list):
        _distribute_unclassified_lookthrough(breakdowns, holding, amount_base)
        return

    breakdown = exposure["breakdown"]
    total_weight = 0.0
    for line in breakdown:
        if isinstance(line, dict):
            weight = line.get("weight_pct")
            if isinstance(weight, (int, float)) and not isinstance(weight, bool):
                total_weight += float(weight)
    if total_weight <= 0:
        _distribute_unclassified_lookthrough(breakdowns, holding, amount_base)
        if warnings is not None:
            hid = str(holding.get("id", "unknown"))
            message = (
                f"Holding '{hid}' has non-positive look-through exposure weight; "
                "assigned exposure to __unclassified__"
            )
            warnings.append(message)
            record_finding(
                findings,
                "RECON_LOOKTHROUGH_NON_POSITIVE_WEIGHT",
                message,
                scope="holding",
                refs={"holding_id": hid},
                suggested_fix=(
                    "Set economic_exposure.breakdown weight_pct values that sum to a positive total."
                ),
            )
        return

    for dim in _LOOKTHROUGH_DIMENSIONS:
        for line in breakdown:
            if not isinstance(line, dict):
                continue
            weight = line.get("weight_pct")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool):
                continue
            bucket = _lookthrough_bucket(dim, line, holding)
            share = amount_base * (float(weight) / total_weight)
            breakdowns[dim][bucket] = breakdowns[dim].get(bucket, 0.0) + share


def _asset_class_index(asset_type_catalog: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in asset_type_catalog:
        type_id = str(item.get("id", "")).strip()
        asset_class = str(item.get("asset_class", "other")).strip() or "other"
        if type_id:
            index[type_id] = asset_class
    return index


def _normalize_fx_rates_to_base(
    fx_rates_to_base: dict[str, Any] | None,
) -> dict[str, float]:
    if not isinstance(fx_rates_to_base, dict):
        return {}

    normalized: dict[str, float] = {}
    for currency, rate in fx_rates_to_base.items():
        code = str(currency).strip().upper()
        if not code:
            continue
        if _is_numeric(rate) and float(rate) > 0:
            normalized[code] = float(rate)
    return normalized


def _lookup_fx_rate(
    currency: str,
    base_currency: str,
    *,
    metadata: Any,
    fx_rates_to_base: dict[str, float],
) -> tuple[float, FxSource] | None:
    """Pure FX rate resolution — no side effects, mirrors `_resolve_to_base_amount`.

    Returned source matches what `_resolve_to_base_amount` would have used so
    trust records and findings stay consistent.
    """

    code = currency.strip().upper()
    if code == base_currency:
        return 1.0, "identity"
    rate = fx_rates_to_base.get(code)
    if rate is not None and rate > 0:
        return float(rate), "fx_rates_to_base"
    metadata_fx = metadata.get("fx_rate_to_base") if isinstance(metadata, dict) else None
    if _is_numeric(metadata_fx) and float(metadata_fx) > 0:
        return float(metadata_fx), "metadata.fx_rate_to_base"
    return None


def _build_holding_trust_record(
    holding: dict[str, Any],
    *,
    asset_class: str,
    base_currency: str,
    base_amount: float | None,
    fx_rates_to_base: dict[str, float],
) -> HoldingTrustRecord:
    holding_id = str(holding.get("id", "unknown"))
    asset_type_id = str(holding.get("asset_type_id", "")).strip()

    market_value = holding.get("market_value")
    if market_value is None:
        return HoldingTrustRecord(
            holding_id=holding_id,
            asset_type_id=asset_type_id,
            asset_class=asset_class,
            source_amount=None,
            source_currency=None,
            base_currency=base_currency,
            base_amount=None,
            fx_rate=None,
            fx_source=None,
            excluded_reason="missing_market_value",
        )

    if not isinstance(market_value, dict):
        return HoldingTrustRecord(
            holding_id=holding_id,
            asset_type_id=asset_type_id,
            asset_class=asset_class,
            source_amount=None,
            source_currency=None,
            base_currency=base_currency,
            base_amount=None,
            fx_rate=None,
            fx_source=None,
            excluded_reason="invalid_money",
        )

    raw_amount = market_value.get("amount")
    raw_currency = market_value.get("currency")
    valid_money = (
        _is_numeric(raw_amount)
        and isinstance(raw_currency, str)
        and bool(raw_currency.strip())
    )
    if not valid_money:
        return HoldingTrustRecord(
            holding_id=holding_id,
            asset_type_id=asset_type_id,
            asset_class=asset_class,
            source_amount=float(raw_amount) if _is_numeric(raw_amount) else None,
            source_currency=raw_currency if isinstance(raw_currency, str) else None,
            base_currency=base_currency,
            base_amount=None,
            fx_rate=None,
            fx_source=None,
            excluded_reason="invalid_money",
        )

    source_amount = float(raw_amount)  # type: ignore[arg-type]
    source_currency = raw_currency.strip().upper()  # type: ignore[union-attr]
    fx = _lookup_fx_rate(
        source_currency,
        base_currency,
        metadata=holding.get("metadata"),
        fx_rates_to_base=fx_rates_to_base,
    )
    if fx is None:
        return HoldingTrustRecord(
            holding_id=holding_id,
            asset_type_id=asset_type_id,
            asset_class=asset_class,
            source_amount=source_amount,
            source_currency=source_currency,
            base_currency=base_currency,
            base_amount=None,
            fx_rate=None,
            fx_source=None,
            excluded_reason="fx_missing",
        )

    fx_rate, fx_source = fx
    return HoldingTrustRecord(
        holding_id=holding_id,
        asset_type_id=asset_type_id,
        asset_class=asset_class,
        source_amount=source_amount,
        source_currency=source_currency,
        base_currency=base_currency,
        base_amount=base_amount,
        fx_rate=fx_rate,
        fx_source=fx_source,
        excluded_reason=None if base_amount is not None else "fx_missing",
    )


def _resolve_to_base_amount(
    amount: float,
    currency: str,
    base_currency: str,
    *,
    metadata: Any,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
    errors: list[str],
    strict: bool,
    context: str,
    scope: str,
    findings: list[Finding] | None = None,
    refs: dict[str, str] | None = None,
) -> float | None:
    currency_code = currency.strip().upper()
    if currency_code == base_currency:
        return amount

    fx_rate = fx_rates_to_base.get(currency_code)
    if fx_rate is not None and fx_rate > 0:
        return amount * fx_rate

    metadata_fx = (
        metadata.get("fx_rate_to_base") if isinstance(metadata, dict) else None
    )
    if _is_numeric(metadata_fx) and float(metadata_fx) > 0:
        message = f"{context} used compatibility fallback metadata.fx_rate_to_base"
        warnings.append(message)
        record_finding(
            findings,
            "TRUST_FX_FALLBACK_USED",
            message,
            scope=scope,
            refs=refs or {},
            observed={"currency": currency_code, "fx_rate": float(metadata_fx)},
            suggested_fix=(
                f"Provide fx_rates_to_base['{currency_code}'] from authoritative FX history "
                "instead of relying on metadata.fx_rate_to_base."
            ),
        )
        return amount * float(metadata_fx)

    message = (
        f"{context} missing base conversion for currency '{currency_code}': "
        f"add fx_rates_to_base['{currency_code}'] or metadata.fx_rate_to_base"
    )
    if strict:
        errors.append(message)
    else:
        warnings.append(message)
    record_finding(
        findings,
        "RECON_FX_MISSING",
        message,
        severity=Severity.ERROR if strict else None,
        scope=scope,
        refs=refs or {},
        observed={"currency": currency_code},
        suggested_fix=(
            f"Add an FX rate for '{currency_code}' -> '{base_currency}' to fx_rates_to_base, "
            "or set metadata.fx_rate_to_base on the affected record."
        ),
    )
    return None


def _report_invalid_money(
    message: str,
    *,
    warnings: list[str],
    errors: list[str],
    strict: bool,
    findings: list[Finding] | None = None,
    scope: str = "",
    refs: dict[str, str] | None = None,
) -> None:
    if strict:
        errors.append(message)
    else:
        warnings.append(message)
    record_finding(
        findings,
        "RECON_INVALID_MONEY",
        message,
        severity=Severity.ERROR if strict else None,
        scope=scope,
        refs=refs or {},
        suggested_fix="Ensure money objects are {amount: number, currency: ISO-4217 code}.",
    )


def _to_base_amount(
    holding: dict[str, Any],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
    errors: list[str],
    strict: bool,
    context: str,
    findings: list[Finding] | None = None,
) -> float | None:
    refs = {"holding_id": str(holding.get("id", "unknown"))}
    market_value = holding.get("market_value")
    if market_value is None:
        return None
    if not isinstance(market_value, dict):
        _report_invalid_money(
            f"{context} has non-object market_value; expected {{amount, currency}}",
            warnings=warnings,
            errors=errors,
            strict=strict,
            findings=findings,
            scope="holding",
            refs=refs,
        )
        return None

    amount = market_value.get("amount")
    currency = market_value.get("currency")
    if not _is_numeric(amount) or not isinstance(currency, str) or not currency.strip():
        _report_invalid_money(
            f"{context} has malformed market_value (amount={amount!r}, currency={currency!r})",
            warnings=warnings,
            errors=errors,
            strict=strict,
            findings=findings,
            scope="holding",
            refs=refs,
        )
        return None

    return _resolve_to_base_amount(
        float(amount),
        currency,
        base_currency,
        metadata=holding.get("metadata"),
        fx_rates_to_base=fx_rates_to_base,
        warnings=warnings,
        errors=errors,
        strict=strict,
        context=context,
        scope="holding",
        findings=findings,
        refs=refs,
    )


def _normalize_identifier(value: str, field: str) -> str:
    normalized = value.strip()
    if field in {"isin", "ticker"}:
        return normalized.upper()
    return normalized


def _collect_identifier_keys(
    asset_type_id: str, identifiers: Any
) -> list[tuple[str, str, str]]:
    if not asset_type_id or not isinstance(identifiers, dict):
        return []
    keys: list[tuple[str, str, str]] = []
    for attr_field in _IDENTIFIER_FIELDS:
        raw = identifiers.get(attr_field)
        if not isinstance(raw, str):
            continue
        normalized = _normalize_identifier(raw, attr_field)
        if normalized:
            keys.append((asset_type_id, attr_field, normalized))
    return keys


def _holding_instrument_keys(holding: dict[str, Any]) -> list[tuple[str, str, str]]:
    return _collect_identifier_keys(
        str(holding.get("asset_type_id", "")).strip(),
        holding.get("identifiers"),
    )


def _activity_instrument_keys(activity: dict[str, Any]) -> list[tuple[str, str, str]]:
    return _collect_identifier_keys(
        str(activity.get("asset_type_id", "")).strip(),
        activity.get("instrument"),
    )


def _is_posted_activity(activity: dict[str, Any]) -> bool:
    status_raw = activity.get("status")
    if status_raw is None:
        return True
    if not isinstance(status_raw, str):
        return False
    status = status_raw.strip().lower()
    return not status or status == "posted"


def _to_base_activity_money_delta(
    activity: dict[str, Any],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
    errors: list[str],
    strict: bool,
    context: str,
    findings: list[Finding] | None = None,
) -> float | None:
    if not _is_posted_activity(activity):
        return None

    event_type = str(activity.get("event_type", "")).strip().lower()
    sign = _CASH_EVENT_SIGNS.get(event_type)
    if sign is None:
        return None

    refs = {"activity_id": str(activity.get("id", "unknown"))}

    money = activity.get("money")
    if money is None:
        return None
    if not isinstance(money, dict):
        _report_invalid_money(
            f"{context} has non-object money; expected {{amount, currency}}",
            warnings=warnings,
            errors=errors,
            strict=strict,
            findings=findings,
            scope="activity",
            refs=refs,
        )
        return None

    amount = money.get("amount")
    currency = money.get("currency")
    if not _is_numeric(amount) or not isinstance(currency, str) or not currency.strip():
        _report_invalid_money(
            f"{context} has malformed money (amount={amount!r}, currency={currency!r})",
            warnings=warnings,
            errors=errors,
            strict=strict,
            findings=findings,
            scope="activity",
            refs=refs,
        )
        return None

    money_base = _resolve_to_base_amount(
        float(amount),
        currency,
        base_currency,
        metadata=activity.get("metadata"),
        fx_rates_to_base=fx_rates_to_base,
        warnings=warnings,
        errors=errors,
        strict=strict,
        context=context,
        scope="activity",
        findings=findings,
        refs=refs,
    )
    if money_base is None:
        return None

    delta = sign * money_base

    fees = activity.get("fees")
    if fees is not None:
        if not isinstance(fees, dict):
            _report_invalid_money(
                f"{context} has non-object fees; expected {{amount, currency}}",
                warnings=warnings,
                errors=errors,
                strict=strict,
                findings=findings,
                scope="activity",
                refs=refs,
            )
        else:
            fee_amount = fees.get("amount")
            fee_currency = fees.get("currency")
            if (
                not _is_numeric(fee_amount)
                or not isinstance(fee_currency, str)
                or not fee_currency.strip()
            ):
                _report_invalid_money(
                    f"{context} has malformed fees (amount={fee_amount!r}, currency={fee_currency!r})",
                    warnings=warnings,
                    errors=errors,
                    strict=strict,
                    findings=findings,
                    scope="activity",
                    refs=refs,
                )
            else:
                fee_base = _resolve_to_base_amount(
                    abs(float(fee_amount)),
                    fee_currency,
                    base_currency,
                    metadata=activity.get("metadata"),
                    fx_rates_to_base=fx_rates_to_base,
                    warnings=warnings,
                    errors=errors,
                    strict=strict,
                    context=f"{context} fees",
                    scope="activity",
                    findings=findings,
                    refs=refs,
                )
                if fee_base is not None:
                    delta -= fee_base

    return delta


def _append_cash_drift_warnings(
    class_index: dict[str, str],
    holdings: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
    errors: list[str],
    strict: bool,
    tolerance_base: float,
    findings: list[Finding] | None = None,
) -> None:
    cash_asset_type_ids = {
        type_id
        for type_id, asset_class in class_index.items()
        if asset_class == "cash_equivalents"
    }
    if not cash_asset_type_ids:
        return

    holdings_cash_base = 0.0
    holdings_cash_count = 0
    for holding in holdings:
        asset_type_id = str(holding.get("asset_type_id", "")).strip()
        if asset_type_id not in cash_asset_type_ids:
            continue

        hid = str(holding.get("id", "unknown"))
        amount_base = _to_base_amount(
            holding,
            base_currency,
            fx_rates_to_base=fx_rates_to_base,
            warnings=warnings,
            errors=errors,
            strict=strict,
            context=f"Cash holding '{hid}'",
            findings=findings,
        )
        if amount_base is None:
            continue

        holdings_cash_base += amount_base
        holdings_cash_count += 1

    ledger_cash_base = 0.0
    ledger_cash_count = 0
    for activity in activities:
        asset_type_id = str(activity.get("asset_type_id", "")).strip()
        if asset_type_id not in cash_asset_type_ids:
            continue

        aid = str(activity.get("id", "unknown"))
        delta = _to_base_activity_money_delta(
            activity,
            base_currency,
            fx_rates_to_base=fx_rates_to_base,
            warnings=warnings,
            errors=errors,
            strict=strict,
            context=f"Cash activity '{aid}'",
            findings=findings,
        )
        if delta is None:
            continue

        ledger_cash_base += delta
        ledger_cash_count += 1

    if holdings_cash_count == 0 or ledger_cash_count == 0:
        return

    drift = holdings_cash_base - ledger_cash_base
    if abs(drift) <= tolerance_base:
        return

    message = (
        f"Cash drift detected: holdings={holdings_cash_base:.2f} {base_currency}, "
        f"activity_ledger={ledger_cash_base:.2f} {base_currency}, drift={drift:+.2f} {base_currency}"
    )
    warnings.append(message)
    record_finding(
        findings,
        "RECON_CASH_DRIFT",
        message,
        scope="portfolio",
        observed={
            "holdings_cash_base": (holdings_cash_base),
            "ledger_cash_base": (ledger_cash_base),
            "drift_base": (drift),
            "base_currency": base_currency,
        },
        expected={"drift_within_base": tolerance_base},
        suggested_fix=(
            "Verify cash holdings balances against the activity ledger; add missing "
            "deposit/withdrawal/dividend events or correct the cash holding amount."
        ),
    )


def aggregate_portfolio(
    portfolio: dict[str, Any],
    *,
    strict: bool = False,
    fx_rates_to_base: dict[str, Any] | None = None,
    quantity_tolerance: float = 1e-6,
    cash_drift_tolerance_base: float = 0.01,
) -> AggregateResult:
    check_financial_contract(portfolio)
    settings = portfolio.get("settings", {})
    raw_base_currency = (
        settings.get("base_currency") if isinstance(settings, dict) else None
    )
    if isinstance(raw_base_currency, str) and raw_base_currency.strip():
        base_currency = raw_base_currency.strip().upper()
    else:
        raise ValueError("settings.base_currency is required for valuation")

    catalog = portfolio.get("asset_type_catalog", [])
    holdings = portfolio.get("holdings", [])
    activities = effective_activities(portfolio.get("activities") or [])
    class_index = _asset_class_index(catalog if isinstance(catalog, list) else [])
    catalog_exposures = _catalog_exposure_index(
        catalog if isinstance(catalog, list) else []
    )
    normalized_fx_rates = _normalize_fx_rates_to_base(fx_rates_to_base)

    by_asset_class: dict[str, float] = {}
    by_account: dict[str, float] = {}
    breakdowns: dict[str, dict[str, float]] = {
        dim: {} for dim in _LOOKTHROUGH_DIMENSIONS
    }
    warnings: list[str] = []
    errors: list[str] = []
    findings: list[Finding] = []
    trust_records: list[HoldingTrustRecord] = []

    for holding in holdings if isinstance(holdings, list) else []:
        if not isinstance(holding, dict):
            message = "Skipped malformed holding entry"
            warnings.append(message)
            record_finding(
                findings,
                "RECON_MALFORMED_HOLDING",
                message,
                scope="portfolio",
                suggested_fix="Ensure each holding entry is a JSON object with the expected fields.",
            )
            continue

        hid = str(holding.get("id", "unknown"))
        amount_base = _to_base_amount(
            holding,
            base_currency,
            fx_rates_to_base=normalized_fx_rates,
            warnings=warnings,
            errors=errors,
            strict=strict,
            context=f"Holding '{hid}'",
            findings=findings,
        )

        asset_type_id = str(holding.get("asset_type_id", ""))
        asset_class = class_index.get(asset_type_id, "other")
        trust_records.append(
            _build_holding_trust_record(
                holding,
                asset_class=asset_class,
                base_currency=base_currency,
                base_amount=amount_base,
                fx_rates_to_base=normalized_fx_rates,
            )
        )

        if amount_base is None:
            continue

        by_asset_class[asset_class] = by_asset_class.get(asset_class, 0.0) + amount_base

        raw_account_id = holding.get("account_id")
        account_key = (
            raw_account_id.strip()
            if isinstance(raw_account_id, str) and raw_account_id.strip()
            else UNASSIGNED_ACCOUNT
        )
        by_account[account_key] = by_account.get(account_key, 0.0) + amount_base

        exposure = _resolve_holding_exposure(holding, asset_type_id, catalog_exposures)
        _distribute_lookthrough(
            breakdowns, exposure, holding, amount_base, warnings, findings=findings
        )

    normalized_holdings = (
        [h for h in holdings if isinstance(h, dict)]
        if isinstance(holdings, list)
        else []
    )
    normalized_activities = (
        [a for a in activities if isinstance(a, dict)]
        if isinstance(activities, list)
        else []
    )

    diagnostics = portfolio_import_diagnostics(portfolio)
    quantity_results = reconcile_quantities(normalized_holdings, normalized_activities, diagnostics, tolerance=quantity_tolerance)
    for comparison in quantity_results:
        if comparison["status"] == "mismatched":
            message = f"Quantity drift for holding '{comparison['holding_id']}': holding={comparison['holding_quantity']}, ledger={comparison['ledger_quantity']}"
            warnings.append(message)
            record_finding(findings, "RECON_QTY_LEDGER_MISMATCH", message, scope="holding", refs={"holding_id": comparison["holding_id"]}, observed=comparison, expected={"drift_within": quantity_tolerance}, suggested_fix="Review dated movements, source coverage, and the reported position.")
    _append_cash_drift_warnings(
        class_index,
        normalized_holdings,
        normalized_activities,
        base_currency,
        fx_rates_to_base=normalized_fx_rates,
        warnings=warnings,
        errors=errors,
        strict=strict,
        tolerance_base=cash_drift_tolerance_base,
        findings=findings,
    )

    records_by_holding_id: dict[str, HoldingTrustRecord] = {
        r.holding_id: r for r in trust_records
    }
    for finding in findings:
        hid = finding.refs.get("holding_id") if finding.refs else None
        if not hid:
            continue
        record = records_by_holding_id.get(hid)
        if record is not None and finding.code not in record.findings:
            record.findings.append(finding.code)

    total_value = sum(by_asset_class.values())
    return AggregateResult(
        base_currency=base_currency,
        total_value_base=total_value,
        by_asset_class=dict(sorted(by_asset_class.items())),
        warnings=warnings,
        errors=errors,
        by_region=dict(sorted(breakdowns["region"].items())),
        by_currency=dict(sorted(breakdowns["currency"].items())),
        by_duration=dict(sorted(breakdowns["duration"].items())),
        by_liquidity_tier={
            k: v for k, v in sorted(breakdowns["liquidity_tier"].items())
        },
        by_account=dict(sorted(by_account.items())),
        findings=findings,
        trust_records=trust_records,
        quantity_reconciliation=quantity_results,
        import_diagnostics=diagnostics,
    )


def portfolio_import_diagnostics(portfolio: dict[str, Any]) -> dict[str, Any]:
    state = (portfolio.get("extensions") or {}).get("rikdom_import_diagnostics", {})
    result: dict[str, Any] = {"version": 1, "history_coverage": [], "unsupported_events": []}
    for diagnostics in state.get("statements", {}).values():
        from .import_preflight import validate_import_diagnostics
        errors = validate_import_diagnostics(diagnostics)
        if errors:
            raise ValueError("; ".join(errors))
        result["history_coverage"].extend(diagnostics["history_coverage"])
        result["unsupported_events"].extend(diagnostics["unsupported_events"])
    return result


def reconcile_quantities(holdings: list[dict[str, Any]], activities: list[dict[str, Any]], diagnostics: dict[str, Any], *, tolerance: float) -> list[dict[str, Any]]:
    """Compare only account-scoped, dated positions backed by explicit evidence."""
    results = []
    for holding in holdings:
        if not _is_numeric(holding.get("quantity")):
            continue
        hid, account = holding.get("id"), holding.get("account_id")
        result: dict[str, Any] = {"holding_id": hid, "status": "not_computable", "reason": "Explicit account-scoped history and dated trade-basis position required"}
        results.append(result)
        declarations = [c for c in diagnostics["history_coverage"] if c.get("holding_id") == hid and account and c.get("account_id") == account]
        if len(declarations) != 1:
            continue
        c = declarations[0]
        if c.get("status") != "complete" or c.get("history_origin") != "inception" or c.get("opening_quantity") != 0 or c.get("position_basis") != "trade" or not c.get("evidence") or not {"buy", "sell"}.issubset(set(c.get("event_types", []))):
            continue
        try:
            zone = ZoneInfo(c["timezone"])
            position = datetime.fromisoformat(holding["as_of"].replace("Z", "+00:00"))
            if position.tzinfo is None:
                continue
            start = datetime.combine(date.fromisoformat(c["from"]), time.min, zone)
            end = datetime.combine(date.fromisoformat(c["through"]) + timedelta(days=1), time.min, zone)
            if not start <= position < end:
                result["reason"] = "Declared coverage does not reach the position timestamp"
                continue
        except (KeyError, ValueError, TypeError):
            continue
        if any(e.get("affects_quantity", True) and e.get("scope", c["scope"]) == c["scope"] for e in diagnostics["unsupported_events"]):
            result["reason"] = "Unsupported quantity movements in the source scope"
            continue
        ledger = 0.0
        invalid = False
        refs = []
        for a in activities:
            if not _is_posted_activity(a):
                continue
            action = a.get("corporate_action")
            leg_match = isinstance(action, dict) and any(isinstance(leg, dict) and leg.get("holding_id") == hid for leg in action.get("legs", []))
            if a.get("account_id") != account:
                if a.get("holding_id") == hid or leg_match or (not a.get("account_id") and set(_holding_instrument_keys(holding)) & set(_activity_instrument_keys(a))):
                    invalid = True
                continue
            if leg_match:
                matches = True
            elif a.get("holding_id"):
                matches = a["holding_id"] == hid
            else:
                keys = set(_holding_instrument_keys(holding)) & set(_activity_instrument_keys(a))
                owners = [h for h in holdings if h.get("account_id") == account and set(_holding_instrument_keys(h)) & set(_activity_instrument_keys(a))]
                matches = bool(keys) and len(owners) == 1
                if keys and len(owners) != 1:
                    invalid = True
            if not matches:
                continue
            h_isin = (holding.get("identifiers") or {}).get("isin")
            a_isin = (a.get("instrument") or {}).get("isin")
            if h_isin and a_isin and str(h_isin).strip().upper() != str(a_isin).strip().upper():
                invalid = True
                continue
            event = a.get("event_type")
            if event not in _QUANTITY_EVENT_SIGNS and "corporate_action" not in a:
                if a.get("quantity"):
                    invalid = True
                continue
            if event not in c.get("event_types", []):
                invalid = True
                continue
            when = a.get("trade_at") or (a.get("effective_at") if c.get("effective_at_basis") == "trade" else None)
            try:
                timestamp = datetime.fromisoformat(when.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("Ambiguous movement timestamp")
                if timestamp < start:
                    invalid = True
                    continue
                if timestamp > position:
                    continue
                action = a.get("corporate_action")
                if action:
                    legs = [leg for leg in action["legs"] if leg.get("holding_id") == hid]
                    delta = sum(float(leg["quantity_delta"]) for leg in legs)
                    if not legs:
                        raise ValueError("Missing quantity legs")
                else:
                    quantity = a["quantity"]
                    if not _is_numeric(quantity):
                        raise ValueError("Invalid quantity")
                    delta = _QUANTITY_EVENT_SIGNS[event] * float(quantity)
                ledger += delta
                refs.append(a.get("id"))
            except (KeyError, ValueError, TypeError, AttributeError):
                invalid = True
        if invalid:
            result["reason"] = "Ambiguous or unsupported quantity movement"
            continue
        result.update(status="matched" if abs(float(holding["quantity"]) - ledger) <= tolerance else "mismatched", reason="Declared history compared on trade basis", ledger_quantity=ledger, holding_quantity=float(holding["quantity"]), activity_ids=refs)
    return results
