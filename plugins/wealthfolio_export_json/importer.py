#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rikdom.import_normalization import as_text, normalize_currency, normalize_datetime, parse_decimal

PROVIDER = "wealthfolio_export_json"

_ACTIVITY_TYPE_MAP: dict[str, str] = {
    "buy": "buy",
    "sell": "sell",
    "dividend": "dividend",
    "interest": "interest",
    "deposit": "transfer_in",
    "withdrawal": "transfer_out",
    "fee": "fee",
    "transfer_in": "transfer_in",
    "transfer-in": "transfer_in",
    "transfer_out": "transfer_out",
    "transfer-out": "transfer_out",
    "conversion_in": "transfer_in",
    "conversion_out": "transfer_out",
    "split": "split",
    "add_holding": "transfer_in",
    "remove_holding": "transfer_out",
    "tax": "other",
    "tax_refund": "other",
    "income": "dividend",
}

_ASSET_TYPE_MAP: dict[str, str] = {
    "equity": "stock",
    "stock": "stock",
    "etf": "etf",
    "mutual_fund": "fund",
    "mutualfund": "fund",
    "fund": "fund",
    "bond": "bond",
    "fixed_income": "bond",
    "cash": "cash",
    "currency": "cash",
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "real_estate": "real_estate",
    "commodity": "commodity",
}

_NEGATIVE_CASHFLOW = {"buy", "transfer_out", "fee"}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, item: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(item, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:16]}"


def _load_payload(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"activities": raw}
    raise ValueError("Wealthfolio export must be a JSON object or array")


def _pick(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _extract_rows(payload: dict[str, Any], primary_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in primary_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for envelope in ("data", "result", "export"):
        nested = payload.get(envelope)
        if isinstance(nested, dict):
            rows = _extract_rows(nested, primary_keys)
            if rows:
                return rows

    rows: list[dict[str, Any]] = []
    grouping = payload.get("accounts")
    if isinstance(grouping, list):
        for account in grouping:
            if not isinstance(account, dict):
                continue
            for key in primary_keys:
                inner = account.get(key)
                if isinstance(inner, list):
                    rows.extend(item for item in inner if isinstance(item, dict))
    return rows


def _normalize_activity_type(raw: Any) -> tuple[str, str]:
    text = as_text(raw).lower().replace("-", "_")
    return _ACTIVITY_TYPE_MAP.get(text, "other"), text


def _signed_amount(event_type: str, magnitude: float, raw_value: float | None) -> float:
    if raw_value is not None and raw_value != 0:
        return raw_value
    if event_type in _NEGATIVE_CASHFLOW:
        return -abs(magnitude)
    return abs(magnitude)


def _instrument_from(item: dict[str, Any], asset: dict[str, Any] | None) -> dict[str, Any]:
    instrument: dict[str, Any] = {}
    ticker = as_text(_pick(item, "symbol", "ticker", "asset_symbol"))
    if not ticker and asset:
        ticker = as_text(_pick(asset, "symbol", "ticker"))
    if ticker:
        instrument["ticker"] = ticker
    isin = as_text(_pick(item, "isin"))
    if not isin and asset:
        isin = as_text(_pick(asset, "isin"))
    if isin:
        instrument["isin"] = isin
    name = as_text(_pick(item, "asset_name", "name"))
    if not name and asset:
        name = as_text(_pick(asset, "name"))
    if name:
        instrument["name"] = name
    return instrument


def _normalize_activity(item: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    activity_id = as_text(_pick(item, "id", "activityId", "activity_id")) or _stable_id(
        "wealthfolio-act", item
    )
    event_type, raw_type = _normalize_activity_type(
        _pick(item, "activity_type", "activityType", "type", "kind")
    )

    raw_effective_at = _pick(item, "activity_date", "activityDate", "date", "transactionDate")
    effective_at = normalize_datetime(raw_effective_at) or as_text(raw_effective_at)
    if not effective_at:
        raise ValueError(
            f"Wealthfolio activity '{activity_id}' is missing an activity_date"
        )

    asset_ref = as_text(_pick(item, "asset_id", "assetId"))
    asset_meta = assets.get(asset_ref) if asset_ref else None

    currency = normalize_currency(
        _pick(item, "currency", "currencyCode", "transaction_currency")
    )
    if not currency and asset_meta:
        currency = normalize_currency(_pick(asset_meta, "currency"))
    if not currency:
        raise ValueError(
            f"Wealthfolio activity '{activity_id}' has no resolvable currency"
        )

    quantity = parse_decimal(_pick(item, "quantity", "shares", "units"))
    unit_price = parse_decimal(_pick(item, "unit_price", "unitPrice", "price"))
    explicit_amount = parse_decimal(_pick(item, "amount", "value", "net_amount", "total"))
    fee_amount = parse_decimal(_pick(item, "fee", "fees", "feeAmount"))

    if explicit_amount is not None:
        magnitude = abs(explicit_amount)
        raw_value = explicit_amount
    elif quantity is not None and unit_price is not None:
        magnitude = abs(quantity) * unit_price
        raw_value = None
    elif quantity is not None and event_type in {"transfer_in", "transfer_out", "dividend", "interest"}:
        magnitude = abs(quantity)
        raw_value = None
    else:
        raise ValueError(
            f"Wealthfolio activity '{activity_id}' has no resolvable amount/value"
        )

    amount = _signed_amount(event_type, magnitude, raw_value)

    activity: dict[str, Any] = {
        "id": f"wealthfolio-{activity_id}",
        "event_type": event_type,
        "effective_at": effective_at,
        "status": "pending" if bool(_pick(item, "is_draft", "isDraft")) else "posted",
        "money": {"amount": amount, "currency": currency},
        "source_ref": as_text(_pick(item, "account_id", "accountId")) or f"{PROVIDER}#{activity_id}",
        "metadata": {
            "raw_activity_type": raw_type,
        },
    }
    if event_type == "other" and raw_type:
        activity["subtype"] = f"wealthfolio:{raw_type}"

    if quantity is not None:
        activity["quantity"] = abs(quantity)

    if fee_amount is not None and fee_amount != 0:
        activity["fees"] = {"amount": abs(fee_amount), "currency": currency}

    instrument = _instrument_from(item, asset_meta)
    if instrument:
        activity["instrument"] = instrument

    return activity


def _normalize_holding(item: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    asset_ref = as_text(_pick(item, "asset_id", "assetId", "symbol", "ticker"))
    asset_meta = assets.get(asset_ref) if asset_ref else None

    holding_id = as_text(_pick(item, "id", "holdingId")) or asset_ref or _stable_id(
        "wealthfolio-h", item
    )

    raw_asset_type = as_text(
        _pick(item, "asset_type", "assetType", "asset_class", "assetClass")
    )
    if not raw_asset_type and asset_meta:
        raw_asset_type = as_text(_pick(asset_meta, "asset_type", "asset_class"))
    asset_type_id = _ASSET_TYPE_MAP.get(raw_asset_type.lower(), raw_asset_type.lower() or "other")

    quantity = parse_decimal(_pick(item, "quantity", "shares", "units"))
    market_value = parse_decimal(
        _pick(item, "market_value", "marketValue", "value", "current_value")
    )
    currency = normalize_currency(
        _pick(item, "currency", "currencyCode", "market_value_currency")
    )
    if not currency and asset_meta:
        currency = normalize_currency(_pick(asset_meta, "currency"))
    if market_value is None or not currency:
        raise ValueError(
            f"Wealthfolio holding '{holding_id}' is missing market_value/currency"
        )

    label = as_text(_pick(item, "name", "label"))
    if not label and asset_meta:
        label = as_text(_pick(asset_meta, "name"))
    if not label:
        label = asset_ref or holding_id

    holding: dict[str, Any] = {
        "id": f"wealthfolio-{holding_id}",
        "asset_type_id": asset_type_id,
        "label": label,
        "market_value": {"amount": market_value, "currency": currency},
    }
    if quantity is not None:
        holding["quantity"] = quantity

    instrument = _instrument_from(item, asset_meta)
    if instrument:
        identifiers: dict[str, Any] = {}
        if "ticker" in instrument:
            identifiers["ticker"] = instrument["ticker"]
        if "isin" in instrument:
            identifiers["isin"] = instrument["isin"]
        if identifiers:
            holding["identifiers"] = identifiers

    source_ref = as_text(_pick(item, "account_id", "accountId"))
    if source_ref:
        holding["provenance"] = {"source_ref": source_ref}

    return holding


def _index_assets(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = _extract_rows(payload, ("assets",))
    index: dict[str, dict[str, Any]] = {}
    for asset in rows:
        for key in ("id", "asset_id", "symbol", "ticker"):
            value = as_text(asset.get(key))
            if value:
                index.setdefault(value, asset)
    return index


def parse_export(path: Path) -> dict[str, Any]:
    payload = _load_payload(path)
    assets = _index_assets(payload)

    raw_activities = _extract_rows(payload, ("activities", "transactions"))
    raw_holdings = _extract_rows(payload, ("holdings", "positions"))

    activities = [_normalize_activity(item, assets) for item in raw_activities]
    holdings = [_normalize_holding(item, assets) for item in raw_holdings]

    if not activities and not holdings:
        raise ValueError("Wealthfolio export did not contain holdings or activities")

    generated_at = (
        normalize_datetime(_pick(payload, "generated_at", "generatedAt", "exported_at", "exportedAt"))
        or _now_iso()
    )
    result: dict[str, Any] = {
        "provider": PROVIDER,
        "generated_at": generated_at,
    }
    if holdings:
        result["holdings"] = holdings
    if activities:
        result["activities"] = activities
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <wealthfolio-export.json>", file=sys.stderr)
        return 1
    payload = parse_export(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
