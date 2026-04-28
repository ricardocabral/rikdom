from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeGuard

from rikdom.reconciliation import Finding, record_finding


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
    findings: list[Finding] = field(default_factory=list)


UNCLASSIFIED = "__unclassified__"
_LOOKTHROUGH_DIMENSIONS = ("region", "currency", "duration", "liquidity_tier")


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
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
            scope=context,
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
        scope=context,
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
            scope=context,
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
            scope=context,
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


def _build_quantity_ledger_index(
    activities: list[dict[str, Any]],
) -> tuple[
    list[float | None],
    dict[tuple[str, str, str], set[int]],
    list[set[str]],
]:
    deltas: list[float | None] = []
    key_index: dict[tuple[str, str, str], set[int]] = {}
    activity_identifier_fields: list[set[str]] = []

    for idx, activity in enumerate(activities):
        if not _is_posted_activity(activity):
            deltas.append(None)
            activity_identifier_fields.append(set())
            continue
        event_type = str(activity.get("event_type", "")).strip().lower()
        sign = _QUANTITY_EVENT_SIGNS.get(event_type)
        if sign is None:
            deltas.append(None)
            activity_identifier_fields.append(set())
            continue

        quantity = activity.get("quantity")
        if not _is_numeric(quantity):
            deltas.append(None)
            activity_identifier_fields.append(set())
            continue

        keys = _activity_instrument_keys(activity)
        activity_identifier_fields.append({field for _, field, _ in keys})
        if not keys:
            deltas.append(None)
            continue

        deltas.append(sign * float(quantity))
        for key in keys:
            key_index.setdefault(key, set()).add(idx)

    return deltas, key_index, activity_identifier_fields


def _append_quantity_consistency_warnings(
    holdings: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    warnings: list[str],
    *,
    tolerance: float,
    findings: list[Finding] | None = None,
) -> None:
    deltas, key_index, activity_identifier_fields = _build_quantity_ledger_index(
        activities
    )
    if not key_index:
        return

    for holding in holdings:
        quantity = holding.get("quantity")
        if not _is_numeric(quantity):
            continue

        keys = _holding_instrument_keys(holding)
        if not keys:
            continue

        keys_by_field: dict[str, list[tuple[str, str, str]]] = {}
        for key in keys:
            keys_by_field.setdefault(key[1], []).append(key)

        matching_indices: set[int] = set()
        for identifier_field in _HIGH_CONFIDENCE_IDENTIFIER_FIELDS:
            for key in keys_by_field.get(identifier_field, ()):
                matching_indices.update(key_index.get(key, ()))

        holding_has_high_confidence = any(
            identifier_field in keys_by_field
            for identifier_field in _HIGH_CONFIDENCE_IDENTIFIER_FIELDS
        )
        if not matching_indices and not holding_has_high_confidence:
            for identifier_field in _LOW_CONFIDENCE_IDENTIFIER_FIELDS:
                indices_for_field: set[int] = set()
                for key in keys_by_field.get(identifier_field, ()):
                    indices_for_field.update(key_index.get(key, ()))
                if not indices_for_field:
                    continue
                matching_indices = {
                    idx
                    for idx in indices_for_field
                    if not (
                        activity_identifier_fields[idx]
                        & _HIGH_CONFIDENCE_IDENTIFIER_FIELDS_SET
                    )
                }
                if matching_indices:
                    break
        if not matching_indices:
            continue

        ledger_qty = sum(
            delta
            for i in matching_indices
            for delta in (deltas[i],)
            if delta is not None
        )
        holding_qty = float(quantity)
        drift = holding_qty - ledger_qty
        if abs(drift) <= tolerance:
            continue

        hid = str(holding.get("id", "unknown"))
        message = (
            f"Quantity drift for holding '{hid}': "
            f"holding={holding_qty:.6f}, ledger={ledger_qty:.6f}, drift={drift:+.6f}"
        )
        warnings.append(message)
        record_finding(
            findings,
            "RECON_QTY_LEDGER_MISMATCH",
            message,
            scope="holding",
            refs={"holding_id": hid},
            observed={"holding_quantity": holding_qty, "ledger_quantity": ledger_qty},
            expected={"drift_within": tolerance},
            suggested_fix=(
                "Reconcile activity ledger entries against the declared holding quantity: "
                "fix missing buy/sell/transfer/split events or correct the holding quantity."
            ),
        )


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
            scope=context,
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
            scope=context,
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
                scope=context,
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
                    scope=context,
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
            "holdings_cash_base": round(holdings_cash_base, 2),
            "ledger_cash_base": round(ledger_cash_base, 2),
            "drift_base": round(drift, 2),
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
    settings = portfolio.get("settings", {})
    raw_base_currency = (
        settings.get("base_currency") if isinstance(settings, dict) else None
    )
    if isinstance(raw_base_currency, str) and raw_base_currency.strip():
        base_currency = raw_base_currency.strip().upper()
    else:
        base_currency = "USD"

    catalog = portfolio.get("asset_type_catalog", [])
    holdings = portfolio.get("holdings", [])
    activities = portfolio.get("activities", [])
    class_index = _asset_class_index(catalog if isinstance(catalog, list) else [])
    catalog_exposures = _catalog_exposure_index(
        catalog if isinstance(catalog, list) else []
    )
    normalized_fx_rates = _normalize_fx_rates_to_base(fx_rates_to_base)

    by_asset_class: dict[str, float] = {}
    breakdowns: dict[str, dict[str, float]] = {
        dim: {} for dim in _LOOKTHROUGH_DIMENSIONS
    }
    warnings: list[str] = []
    errors: list[str] = []
    findings: list[Finding] = []

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
        if amount_base is None:
            continue

        asset_type_id = str(holding.get("asset_type_id", ""))
        asset_class = class_index.get(asset_type_id, "other")
        by_asset_class[asset_class] = by_asset_class.get(asset_class, 0.0) + amount_base

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

    _append_quantity_consistency_warnings(
        normalized_holdings,
        normalized_activities,
        warnings,
        tolerance=quantity_tolerance,
        findings=findings,
    )
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

    total_value = sum(by_asset_class.values())
    return AggregateResult(
        base_currency=base_currency,
        total_value_base=round(total_value, 2),
        by_asset_class={k: round(v, 2) for k, v in sorted(by_asset_class.items())},
        warnings=warnings,
        errors=errors,
        by_region={k: round(v, 2) for k, v in sorted(breakdowns["region"].items())},
        by_currency={k: round(v, 2) for k, v in sorted(breakdowns["currency"].items())},
        by_duration={k: round(v, 2) for k, v in sorted(breakdowns["duration"].items())},
        by_liquidity_tier={
            k: round(v, 2) for k, v in sorted(breakdowns["liquidity_tier"].items())
        },
        findings=findings,
    )
