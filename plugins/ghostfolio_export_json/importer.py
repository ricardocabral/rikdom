#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from rikdom.import_normalization import as_text, normalize_currency, normalize_datetime as _normalize_datetime, parse_decimal as _parse_decimal

# This export dialect uses ISO dates and UTC for dates without a zone.
normalize_datetime = partial(_normalize_datetime, naive_timezone=timezone.utc)
parse_decimal = partial(_parse_decimal, decimal_separator=".", grouping_separator=None)

PROVIDER = "ghostfolio_export_json"

_EVENT_TYPE_MAP = {
    "buy": "buy",
    "sell": "sell",
    "dividend": "dividend",
    "interest": "interest",
    "income": "income",
    "tax": "tax_withheld",
    "tax_refund": "tax_withheld",
    "withholding_tax": "tax_withheld",
    "tax_withheld": "tax_withheld",
    "fee": "fee",
    "deposit": "transfer_in",
    "withdrawal": "transfer_out",
    "split": "split",
}

_ASSET_TYPE_MAP = {
    "stock": "stock",
    "stocks": "stock",
    "etf": "etf",
    "fund": "fund",
    "bond": "bond",
    "cash": "cash",
    "crypto": "crypto",
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_payload(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"activities": raw}
    raise ValueError("Ghostfolio export must be a JSON object or array")


def _pick_path(item: dict[str, Any], path: str) -> Any:
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _pick(item: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value = _pick_path(item, path)
        if value is not None and as_text(value):
            return value
    return None


def _extract_rows(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        values = payload.get(key)
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]

    for key in ("data", "result", "export"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            rows = _extract_rows(nested, keys)
            if rows:
                return rows

    rows: list[dict[str, Any]] = []
    for key in ("accounts", "portfolios"):
        grouped = payload.get(key)
        if not isinstance(grouped, list):
            continue
        for item in grouped:
            if not isinstance(item, dict):
                continue
            for nested_key in keys:
                nested_rows = item.get(nested_key)
                if isinstance(nested_rows, list):
                    rows.extend([row for row in nested_rows if isinstance(row, dict)])
    return rows


def _stable_id(prefix: str, item: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(item, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:16]}"


def _event_type(value: Any) -> str:
    raw = as_text(value).lower()
    if not raw:
        return "other"
    return _EVENT_TYPE_MAP.get(raw, "other")


def _asset_type_id(item: dict[str, Any]) -> str:
    raw = as_text(_pick(item, "assetType", "assetClass", "type", "class")).lower()
    if not raw:
        return "other"
    return _ASSET_TYPE_MAP.get(raw, raw.replace(" ", "_"))


def _normalize_activity(item: dict[str, Any]) -> dict[str, Any]:
    activity_id = as_text(_pick(item, "id", "transactionId")) or _stable_id("ghostfolio-act", item)
    event_type = _event_type(_pick(item, "type", "kind", "eventType"))
    raw_effective_at = _pick(item, "date", "effectiveAt", "createdAt", "transactionDate")
    effective_at = normalize_datetime(raw_effective_at) or as_text(raw_effective_at)

    activity: dict[str, Any] = {
        "id": activity_id,
        "event_type": event_type,
        "effective_at": effective_at,
        "status": "posted",
        "source_ref": as_text(
            _pick(item, "sourceRef", "accountId", "account.name", "transactionReference")
        )
        or f"{PROVIDER}#{activity_id}",
        "metadata": {
            "raw_type": as_text(_pick(item, "type", "kind", "eventType")),
        },
    }

    if event_type == "other":
        activity["subtype"] = "ghostfolio:" + (activity["metadata"]["raw_type"] or "unknown")

    quantity = parse_decimal(_pick(item, "quantity", "shares", "units"))
    if quantity is not None:
        activity["quantity"] = quantity

    currency = normalize_currency(
        _pick(item, "currency", "currencyCode", "valueCurrency", "accountCurrency")
    )
    amount_basis = "unknown"
    for field, aliases, currency_aliases in (
        ("money", ("amount", "value", "netAmount", "grossAmount"),
         ("currency", "currencyCode", "valueCurrency", "accountCurrency")),
        ("fees", ("fee", "fees", "feeAmount"), ("feeCurrency", "feesCurrency")),
        ("withholding_tax", ("withholdingTax", "withholding_tax", "withholdingTaxAmount", "tax", "taxes", "taxAmount"),
         ("withholdingTaxCurrency", "withholding_tax_currency", "taxCurrency", "taxesCurrency")),
    ):
        # Validate every supplied alias, including evidence after the selected
        # alias. An invalid primary or secondary amount must never disappear.
        for alias in aliases:
            raw = item.get(alias)
            if raw is None or raw == "":
                continue
            raw_currency = _pick(item, alias + "Currency", *currency_aliases)
            if isinstance(raw, dict):
                raw_currency = raw.get("currency", raw_currency)
                raw = raw.get("amount")
            value = parse_decimal(raw)
            if value is None:
                raise ValueError(f"Ghostfolio activity '{activity_id}' has invalid {alias}")
            code = normalize_currency(raw_currency) if raw_currency is not None else currency
            if not code:
                raise ValueError(f"Ghostfolio activity '{activity_id}' has invalid or missing {alias} currency")
            if field not in activity:
                activity[field] = {"amount": value, "currency": code}
                if field == "money":
                    amount_basis = {"netAmount": "net", "grossAmount": "gross"}.get(alias, "unknown")

    if event_type in {"dividend", "interest", "income"}:
        activity["metadata"]["rikdom_income"] = {"version": 1, "amount_basis": amount_basis}

    instrument: dict[str, Any] = {}
    ticker = as_text(_pick(item, "symbol", "ticker"))
    if ticker:
        instrument["ticker"] = ticker
    isin = as_text(_pick(item, "isin"))
    if isin:
        instrument["isin"] = isin
    if instrument:
        activity["instrument"] = instrument

    return activity


def _normalize_holding(item: dict[str, Any]) -> dict[str, Any]:
    ticker = as_text(_pick(item, "symbol", "ticker"))
    isin = as_text(_pick(item, "isin"))
    holding_id = as_text(_pick(item, "id")) or ticker or isin or _stable_id("ghostfolio-h", item)
    label = as_text(_pick(item, "name", "label")) or ticker or holding_id

    raw_amount = _pick(item, "marketValue", "value", "currentValue", "balance")
    amount: float | None = None
    raw_currency: Any = _pick(item, "currency", "currencyCode", "accountCurrency")

    raw_amount_value: Any = raw_amount
    if isinstance(raw_amount, dict):
        raw_amount_value = raw_amount.get("amount")
        amount = parse_decimal(raw_amount_value)
        raw_currency = raw_amount.get("currency") or raw_currency
    else:
        amount = parse_decimal(raw_amount)

    market_value: dict[str, Any] = {
        "amount": amount if amount is not None else raw_amount_value,
        "currency": normalize_currency(raw_currency) or as_text(raw_currency),
    }

    holding: dict[str, Any] = {
        "id": holding_id,
        "asset_type_id": _asset_type_id(item),
        "label": label,
        "market_value": market_value,
    }

    quantity = parse_decimal(_pick(item, "quantity", "shares", "units"))
    if quantity is not None:
        holding["quantity"] = quantity

    identifiers: dict[str, Any] = {}
    if ticker:
        identifiers["ticker"] = ticker
    if isin:
        identifiers["isin"] = isin
    if identifiers:
        holding["identifiers"] = identifiers

    source_ref = as_text(_pick(item, "sourceRef", "accountId", "account.name"))
    if source_ref:
        holding["provenance"] = {"source_ref": source_ref}

    if isinstance(item.get("metadata"), dict):
        holding["metadata"] = dict(item["metadata"])

    return holding


def parse_export(path: Path) -> dict[str, Any]:
    payload = _load_payload(path)

    raw_activities = _extract_rows(payload, ("activities", "transactions", "orders"))
    raw_holdings = _extract_rows(payload, ("holdings", "positions", "assets"))

    activities = [_normalize_activity(item) for item in raw_activities]
    holdings = [_normalize_holding(item) for item in raw_holdings]

    generated_at = normalize_datetime(payload.get("generatedAt")) or _now_iso()
    result: dict[str, Any] = {
        "provider": PROVIDER,
        "generated_at": generated_at,
    }
    if holdings:
        result["holdings"] = holdings
    if activities:
        result["activities"] = activities
    if not holdings and not activities:
        raise ValueError("Ghostfolio export did not contain holdings or activities")
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <ghostfolio-export.json>", file=sys.stderr)
        return 1

    payload = parse_export(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
