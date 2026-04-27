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

from rikdom.import_normalization import as_text, normalize_currency, normalize_datetime, parse_decimal

PROVIDER = "portfolio_performance_csv"

_HEADER_ALIASES: dict[str, str] = {
    # English headers
    "date": "date",
    "time": "time",
    "type": "type",
    "value": "value",
    "transaction currency": "currency",
    "gross amount": "gross_amount",
    "currency gross amount": "gross_currency",
    "exchange rate": "exchange_rate",
    "fees": "fees",
    "currency fees": "fees_currency",
    "taxes": "taxes",
    "currency taxes": "taxes_currency",
    "shares": "shares",
    "isin": "isin",
    "wkn": "wkn",
    "ticker symbol": "ticker",
    "security name": "security_name",
    "note": "note",
    "cash account": "cash_account",
    "offset account": "offset_account",
    # German headers
    "datum": "date",
    "uhrzeit": "time",
    "typ": "type",
    "wert": "value",
    "buchungswährung": "currency",
    "buchungswahrung": "currency",
    "bruttobetrag": "gross_amount",
    "währung bruttobetrag": "gross_currency",
    "wahrung bruttobetrag": "gross_currency",
    "wechselkurs": "exchange_rate",
    "gebühren": "fees",
    "gebuhren": "fees",
    "währung gebühren": "fees_currency",
    "wahrung gebuhren": "fees_currency",
    "steuern": "taxes",
    "währung steuern": "taxes_currency",
    "wahrung steuern": "taxes_currency",
    "stück": "shares",
    "stuck": "shares",
    "ticker-symbol": "ticker",
    "wertpapiername": "security_name",
    "notiz": "note",
    "cashkonto": "cash_account",
    "gegenkonto": "offset_account",
}

_TYPE_MAP: dict[str, str] = {
    # English
    "buy": "buy",
    "sell": "sell",
    "dividend": "dividend",
    "interest": "interest",
    "interest charge": "interest",
    "deposit": "transfer_in",
    "removal": "transfer_out",
    "fees": "fee",
    "fees refund": "fee",
    "taxes": "other",
    "tax refund": "other",
    "transfer (inbound)": "transfer_in",
    "transfer (outbound)": "transfer_out",
    "delivery (inbound)": "transfer_in",
    "delivery (outbound)": "transfer_out",
    # German
    "kauf": "buy",
    "verkauf": "sell",
    "dividende": "dividend",
    "zinsen": "interest",
    "zinsbelastung": "interest",
    "einlage": "transfer_in",
    "entnahme": "transfer_out",
    "gebühren": "fee",
    "gebuhren": "fee",
    "gebührenerstattung": "fee",
    "steuern": "other",
    "steuererstattung": "other",
    "einlieferung": "transfer_in",
    "auslieferung": "transfer_out",
    "umbuchung (eingang)": "transfer_in",
    "umbuchung (ausgang)": "transfer_out",
}

_CASHFLOW_NEGATIVE = {"buy", "transfer_out", "fee"}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _detect_delimiter(sample: str) -> str:
    candidates = [";", ",", "\t", "|"]
    counts = {c: sample.count(c) for c in candidates}
    delimiter = max(counts, key=lambda c: counts[c])
    if counts[delimiter] == 0:
        return ","
    return delimiter


def _read_rows(path: Path) -> list[dict[str, str]]:
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError("Portfolio Performance CSV input is empty")
    first_line = raw.split("\n", 1)[0]
    delimiter = _detect_delimiter(first_line)
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
    return f"pp-{digest[:16]}"


def _parse_date(row: dict[str, str], row_id: str) -> str:
    date = row.get("date")
    time = row.get("time")
    if not date:
        raise ValueError(
            f"Portfolio Performance row '{row_id}' is missing required date column"
        )
    candidates: list[str] = []
    if date and time:
        candidates.append(f"{date} {time}")
        candidates.append(f"{date}T{time}")
    candidates.append(date)
    for raw in candidates:
        normalized = normalize_datetime(raw)
        if normalized:
            return normalized
        for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                continue
    raise ValueError(
        f"Portfolio Performance row '{row_id}' has unparseable date '{date}'"
    )


def _resolve_event_type(raw: str) -> str:
    key = raw.strip().lower()
    return _TYPE_MAP.get(key, "other")


def _signed_amount(event_type: str, magnitude: float, raw_value: float | None) -> float:
    if raw_value is not None:
        return raw_value
    if event_type in _CASHFLOW_NEGATIVE:
        return -abs(magnitude)
    return abs(magnitude)


def _normalize_row(row: dict[str, str]) -> dict[str, Any]:
    raw_type = row.get("type", "")
    if not raw_type:
        raise ValueError("Portfolio Performance row is missing required Type column")
    event_type = _resolve_event_type(raw_type)
    row_id = row.get("note") or _stable_id(row)
    effective_at = _parse_date(row, row_id)

    currency = (
        normalize_currency(row.get("currency"))
        or normalize_currency(row.get("gross_currency"))
    )
    if not currency:
        raise ValueError(
            f"Portfolio Performance row '{row_id}' is missing transaction currency"
        )

    raw_value = parse_decimal(row.get("value"))
    gross_amount = parse_decimal(row.get("gross_amount"))
    magnitude = (
        abs(raw_value) if raw_value is not None
        else abs(gross_amount) if gross_amount is not None
        else None
    )
    if magnitude is None:
        raise ValueError(
            f"Portfolio Performance row '{row_id}' has no parseable Value or Gross Amount"
        )

    amount = _signed_amount(event_type, magnitude, raw_value)

    activity: dict[str, Any] = {
        "id": f"pp-{row_id}" if not row_id.startswith("pp-") else row_id,
        "event_type": event_type,
        "effective_at": effective_at,
        "status": "posted",
        "money": {"amount": amount, "currency": currency},
        "source_ref": f"{PROVIDER}#{row_id}",
        "metadata": {
            "raw_type": raw_type,
        },
    }

    if event_type == "other" and raw_type:
        activity["subtype"] = f"pp:{raw_type.strip().lower()}"

    quantity = parse_decimal(row.get("shares"))
    if quantity is not None:
        activity["quantity"] = abs(quantity)

    fees = parse_decimal(row.get("fees"))
    if fees is not None and fees != 0:
        fees_currency = normalize_currency(row.get("fees_currency")) or currency
        activity["fees"] = {"amount": abs(fees), "currency": fees_currency}

    taxes = parse_decimal(row.get("taxes"))
    if taxes is not None and taxes != 0:
        taxes_currency = normalize_currency(row.get("taxes_currency")) or currency
        activity.setdefault("metadata", {})["taxes"] = {
            "amount": abs(taxes),
            "currency": taxes_currency,
        }

    instrument: dict[str, Any] = {}
    ticker = as_text(row.get("ticker"))
    if ticker:
        instrument["ticker"] = ticker
    isin = as_text(row.get("isin"))
    if isin:
        instrument["isin"] = isin
    wkn = as_text(row.get("wkn"))
    if wkn:
        instrument["wkn"] = wkn
    name = as_text(row.get("security_name"))
    if name:
        instrument["name"] = name
    if instrument:
        activity["instrument"] = instrument

    return activity


def parse_export(path: Path) -> dict[str, Any]:
    rows = _read_rows(path)
    if not rows:
        raise ValueError("Portfolio Performance CSV did not contain any data rows")

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
        print("usage: importer.py <portfolio-performance.csv>", file=sys.stderr)
        return 1
    payload = parse_export(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
