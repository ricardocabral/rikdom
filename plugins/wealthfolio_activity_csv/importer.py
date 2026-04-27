#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rikdom.import_normalization import normalize_currency, normalize_datetime, parse_decimal

PROVIDER = "wealthfolio_activity_csv"

_HEADER_ALIASES: dict[str, str] = {
    "date": "date",
    "activity_date": "date",
    "activitydate": "date",
    "symbol": "symbol",
    "ticker": "symbol",
    "asset_symbol": "symbol",
    "isin": "isin",
    "name": "name",
    "asset_name": "name",
    "quantity": "quantity",
    "shares": "quantity",
    "units": "quantity",
    "activity_type": "activity_type",
    "activitytype": "activity_type",
    "type": "activity_type",
    "unit_price": "unit_price",
    "unitprice": "unit_price",
    "price": "unit_price",
    "amount": "amount",
    "value": "amount",
    "currency": "currency",
    "fee": "fee",
    "fees": "fee",
    "account_id": "account_id",
    "accountid": "account_id",
    "account": "account_id",
    "comment": "comment",
    "note": "comment",
    "is_draft": "is_draft",
    "isdraft": "is_draft",
    "id": "id",
    "activity_id": "id",
}

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

_NEGATIVE_CASHFLOW = {"buy", "transfer_out", "fee"}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _detect_delimiter(sample: str) -> str:
    candidates = [",", ";", "\t", "|"]
    counts = {c: sample.count(c) for c in candidates}
    delimiter = max(counts, key=lambda c: counts[c])
    if counts[delimiter] == 0:
        return ","
    return delimiter


def _read_rows(path: Path) -> list[dict[str, str]]:
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError("Wealthfolio activity CSV input is empty")
    delimiter = _detect_delimiter(raw.split("\n", 1)[0])
    reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        if raw_row is None:
            continue
        normalized: dict[str, str] = {}
        for header, value in raw_row.items():
            if header is None:
                continue
            key = _HEADER_ALIASES.get(header.strip().lower())
            if key is None:
                continue
            if value is None:
                continue
            text = value.strip()
            if not text:
                continue
            normalized[key] = text
        if normalized:
            rows.append(normalized)
    return rows


def _stable_id(row: dict[str, str]) -> str:
    digest = hashlib.sha256(
        json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"wf-csv-{digest[:16]}"


def _resolve_event_type(raw: str) -> tuple[str, str]:
    text = raw.strip().lower().replace("-", "_")
    return _ACTIVITY_TYPE_MAP.get(text, "other"), text


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "t"}


def _parse_date(row: dict[str, str], row_id: str) -> str:
    raw = row.get("date")
    if not raw:
        raise ValueError(
            f"Wealthfolio activity CSV row '{row_id}' is missing required date column"
        )
    normalized = normalize_datetime(raw)
    if normalized:
        return normalized
    raise ValueError(
        f"Wealthfolio activity CSV row '{row_id}' has unparseable date '{raw}'"
    )


def _normalize_row(row: dict[str, str]) -> dict[str, Any]:
    activity_id = row.get("id") or _stable_id(row)
    raw_type = row.get("activity_type") or ""
    if not raw_type:
        raise ValueError(
            f"Wealthfolio activity CSV row '{activity_id}' is missing activity_type"
        )
    event_type, normalized_type = _resolve_event_type(raw_type)
    effective_at = _parse_date(row, activity_id)

    currency = normalize_currency(row.get("currency"))
    if not currency:
        raise ValueError(
            f"Wealthfolio activity CSV row '{activity_id}' is missing currency"
        )

    quantity = parse_decimal(row.get("quantity"))
    unit_price = parse_decimal(row.get("unit_price"))
    explicit_amount = parse_decimal(row.get("amount"))
    fee_amount = parse_decimal(row.get("fee"))

    if explicit_amount is not None:
        magnitude = abs(explicit_amount)
        raw_value = explicit_amount
    elif quantity is not None and unit_price is not None:
        magnitude = abs(quantity) * unit_price
        raw_value = None
    elif quantity is not None and event_type in {
        "transfer_in",
        "transfer_out",
        "dividend",
        "interest",
    }:
        magnitude = abs(quantity)
        raw_value = None
    else:
        raise ValueError(
            f"Wealthfolio activity CSV row '{activity_id}' has no resolvable amount"
        )

    if raw_value is not None and raw_value != 0:
        amount = raw_value
    elif event_type in _NEGATIVE_CASHFLOW:
        amount = -abs(magnitude)
    else:
        amount = abs(magnitude)

    is_draft = _parse_bool(row.get("is_draft", ""))

    activity: dict[str, Any] = {
        "id": f"wealthfolio-csv-{activity_id}",
        "event_type": event_type,
        "effective_at": effective_at,
        "status": "pending" if is_draft else "posted",
        "money": {"amount": amount, "currency": currency},
        "source_ref": row.get("account_id") or f"{PROVIDER}#{activity_id}",
        "metadata": {
            "raw_activity_type": normalized_type,
        },
    }
    if event_type == "other" and normalized_type:
        activity["subtype"] = f"wealthfolio:{normalized_type}"

    if quantity is not None:
        activity["quantity"] = abs(quantity)

    if fee_amount is not None and fee_amount != 0:
        activity["fees"] = {"amount": abs(fee_amount), "currency": currency}

    instrument: dict[str, Any] = {}
    symbol = row.get("symbol")
    if symbol:
        instrument["ticker"] = symbol
    isin = row.get("isin")
    if isin:
        instrument["isin"] = isin
    name = row.get("name")
    if name:
        instrument["name"] = name
    if instrument:
        activity["instrument"] = instrument

    comment = row.get("comment")
    if comment:
        activity["metadata"]["comment"] = comment

    return activity


def parse_activity_csv(path: Path) -> dict[str, Any]:
    rows = _read_rows(path)
    if not rows:
        raise ValueError("Wealthfolio activity CSV did not contain any data rows")

    activities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        activity = _normalize_row(row)
        aid = activity["id"]
        if aid in seen:
            continue
        seen.add(aid)
        activities.append(activity)

    return {
        "provider": PROVIDER,
        "generated_at": _now_iso(),
        "activities": activities,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <wealthfolio-activities.csv>", file=sys.stderr)
        return 1
    payload = parse_activity_csv(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
