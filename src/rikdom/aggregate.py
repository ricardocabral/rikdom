from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AggregateResult:
    base_currency: str
    total_value_base: float
    by_asset_class: dict[str, float]
    warnings: list[str]
    errors: list[str] = field(default_factory=list)
    fx_lock: dict[str, Any] | None = None


_IDENTIFIER_FIELDS = ("isin", "ticker", "wallet", "provider_account_id", "id")

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


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _asset_class_index(asset_type_catalog: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in asset_type_catalog:
        type_id = str(item.get("id", "")).strip()
        asset_class = str(item.get("asset_class", "other")).strip() or "other"
        if type_id:
            index[type_id] = asset_class
    return index


def _normalize_fx_rates_to_base(fx_rates_to_base: dict[str, Any] | None) -> dict[str, float]:
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
) -> float | None:
    currency_code = currency.strip().upper()
    if currency_code == base_currency:
        return amount

    fx_rate = fx_rates_to_base.get(currency_code)
    if fx_rate is not None and fx_rate > 0:
        return amount * fx_rate

    metadata_fx = metadata.get("fx_rate_to_base") if isinstance(metadata, dict) else None
    if _is_numeric(metadata_fx) and float(metadata_fx) > 0:
        warnings.append(
            f"{context} used compatibility fallback metadata.fx_rate_to_base"
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
    return None


def _to_base_amount(
    holding: dict[str, Any],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
    errors: list[str],
    strict: bool,
    context: str,
) -> float | None:
    market_value = holding.get("market_value")
    if not isinstance(market_value, dict):
        return None

    amount = market_value.get("amount")
    currency = market_value.get("currency")
    if not _is_numeric(amount) or not isinstance(currency, str) or not currency.strip():
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
    )


def _normalize_identifier(value: str, field: str) -> str:
    normalized = value.strip()
    if field in {"isin", "ticker"}:
        return normalized.upper()
    return normalized


def _pick_identifier(payload: dict[str, Any]) -> tuple[str, str] | None:
    for attr_field in _IDENTIFIER_FIELDS:
        raw = payload.get(attr_field)
        if not isinstance(raw, str):
            continue
        normalized = _normalize_identifier(raw, attr_field)
        if normalized:
            return attr_field, normalized
    return None


def _holding_instrument_key(holding: dict[str, Any]) -> tuple[str, str, str] | None:
    asset_type_id = str(holding.get("asset_type_id", "")).strip()
    identifiers = holding.get("identifiers")
    if not asset_type_id or not isinstance(identifiers, dict):
        return None

    picked = _pick_identifier(identifiers)
    if picked is None:
        return None

    field, value = picked
    return (asset_type_id, field, value)


def _activity_instrument_key(activity: dict[str, Any]) -> tuple[str, str, str] | None:
    asset_type_id = str(activity.get("asset_type_id", "")).strip()
    instrument = activity.get("instrument")
    if not asset_type_id or not isinstance(instrument, dict):
        return None

    picked = _pick_identifier(instrument)
    if picked is None:
        return None

    field, value = picked
    return (asset_type_id, field, value)


def _is_posted_activity(activity: dict[str, Any]) -> bool:
    status_raw = activity.get("status")
    if status_raw is None:
        return True
    if not isinstance(status_raw, str):
        return False
    status = status_raw.strip().lower()
    return not status or status == "posted"


def _quantity_from_activity_ledger(activities: list[dict[str, Any]]) -> dict[tuple[str, str, str], float]:
    ledger: dict[tuple[str, str, str], float] = {}

    for activity in activities:
        if not _is_posted_activity(activity):
            continue
        event_type = str(activity.get("event_type", "")).strip().lower()
        sign = _QUANTITY_EVENT_SIGNS.get(event_type)
        if sign is None:
            continue

        quantity = activity.get("quantity")
        if not _is_numeric(quantity):
            continue

        key = _activity_instrument_key(activity)
        if key is None:
            continue

        ledger[key] = ledger.get(key, 0.0) + (sign * float(quantity))

    return ledger


def _append_quantity_consistency_warnings(
    holdings: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    warnings: list[str],
    *,
    tolerance: float,
) -> None:
    ledger = _quantity_from_activity_ledger(activities)
    if not ledger:
        return

    for holding in holdings:
        quantity = holding.get("quantity")
        if not _is_numeric(quantity):
            continue

        key = _holding_instrument_key(holding)
        if key is None or key not in ledger:
            continue

        holding_qty = float(quantity)
        ledger_qty = float(ledger[key])
        drift = holding_qty - ledger_qty
        if abs(drift) <= tolerance:
            continue

        hid = str(holding.get("id", "unknown"))
        warnings.append(
            f"Quantity drift for holding '{hid}': "
            f"holding={holding_qty:.6f}, ledger={ledger_qty:.6f}, drift={drift:+.6f}"
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
) -> float | None:
    if not _is_posted_activity(activity):
        return None

    event_type = str(activity.get("event_type", "")).strip().lower()
    sign = _CASH_EVENT_SIGNS.get(event_type)
    if sign is None:
        return None

    money = activity.get("money")
    if not isinstance(money, dict):
        return None

    amount = money.get("amount")
    currency = money.get("currency")
    if not _is_numeric(amount) or not isinstance(currency, str):
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
    )
    if money_base is None:
        return None

    delta = sign * money_base

    fees = activity.get("fees")
    if isinstance(fees, dict):
        fee_amount = fees.get("amount")
        fee_currency = fees.get("currency")
        if _is_numeric(fee_amount) and isinstance(fee_currency, str):
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

    warnings.append(
        f"Cash drift detected: holdings={holdings_cash_base:.2f} {base_currency}, "
        f"activity_ledger={ledger_cash_base:.2f} {base_currency}, drift={drift:+.2f} {base_currency}"
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
    base_currency = str(settings.get("base_currency", "USD")).upper().strip() or "USD"

    catalog = portfolio.get("asset_type_catalog", [])
    holdings = portfolio.get("holdings", [])
    activities = portfolio.get("activities", [])
    class_index = _asset_class_index(catalog if isinstance(catalog, list) else [])
    normalized_fx_rates = _normalize_fx_rates_to_base(fx_rates_to_base)

    by_asset_class: dict[str, float] = {}
    warnings: list[str] = []
    errors: list[str] = []

    for holding in holdings if isinstance(holdings, list) else []:
        if not isinstance(holding, dict):
            warnings.append("Skipped malformed holding entry")
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
        )
        if amount_base is None:
            continue

        asset_type_id = str(holding.get("asset_type_id", ""))
        asset_class = class_index.get(asset_type_id, "other")
        by_asset_class[asset_class] = by_asset_class.get(asset_class, 0.0) + amount_base

    normalized_holdings = [h for h in holdings if isinstance(h, dict)] if isinstance(holdings, list) else []
    normalized_activities = [a for a in activities if isinstance(a, dict)] if isinstance(activities, list) else []

    _append_quantity_consistency_warnings(
        normalized_holdings,
        normalized_activities,
        warnings,
        tolerance=quantity_tolerance,
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
    )

    total_value = sum(by_asset_class.values())
    return AggregateResult(
        base_currency=base_currency,
        total_value_base=round(total_value, 2),
        by_asset_class={k: round(v, 2) for k, v in sorted(by_asset_class.items())},
        warnings=warnings,
        errors=errors,
    )
