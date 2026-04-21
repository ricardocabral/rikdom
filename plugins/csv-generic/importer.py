#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_rows(path: Path) -> list[dict[str, str | None]]:
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def _cell(row: dict[str, str | None], field: str) -> str:
    return (row.get(field) or "").strip()


def _required_cell(row: dict[str, str | None], field: str, *, context: str) -> str:
    if field not in row:
        raise ValueError(f"Invalid {context} row: missing required column '{field}'")
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"Invalid {context} row: required field '{field}' is empty")
    return value


def _to_holding(row: dict[str, str | None]) -> dict:
    amount = float(_required_cell(row, "amount", context="holding"))
    holding = {
        "id": _required_cell(row, "id", context="holding"),
        "asset_type_id": _required_cell(row, "asset_type_id", context="holding"),
        "label": _required_cell(row, "label", context="holding"),
        "market_value": {
            "amount": amount,
            "currency": _required_cell(row, "currency", context="holding").upper(),
        },
    }

    quantity = _cell(row, "quantity")
    if quantity:
        holding["quantity"] = float(quantity)

    ticker = _cell(row, "ticker")
    if ticker:
        holding["identifiers"] = {"ticker": ticker}

    country = _cell(row, "country").upper()
    if country:
        holding["jurisdiction"] = {"country": country}

    fx_rate = _cell(row, "fx_rate_to_base")
    if fx_rate:
        holding["metadata"] = {"fx_rate_to_base": float(fx_rate)}

    return holding


def _to_activity(row: dict[str, str | None]) -> dict:
    activity_id = _required_cell(row, "id", context="activity")
    amount = float(_required_cell(row, "amount", context="activity"))
    currency = _required_cell(row, "currency", context="activity").upper()
    event_type = _cell(row, "event_type") or "other"
    effective_at = _cell(row, "effective_at")
    if not effective_at:
        raise ValueError(
            f"Invalid activity row id='{activity_id}': missing required effective_at"
        )

    activity: dict = {
        "id": activity_id,
        "event_type": event_type,
        "status": _cell(row, "status") or "posted",
        "effective_at": effective_at,
        "money": {"amount": amount, "currency": currency},
    }

    asset_type_id = _cell(row, "asset_type_id")
    if asset_type_id:
        activity["asset_type_id"] = asset_type_id

    subtype = _cell(row, "subtype")
    if subtype:
        activity["subtype"] = subtype

    quantity = _cell(row, "quantity")
    if quantity:
        activity["quantity"] = float(quantity)

    instrument: dict = {}
    ticker = _cell(row, "ticker")
    if ticker:
        instrument["ticker"] = ticker
    country = _cell(row, "country").upper()
    if country:
        instrument["country"] = country
    if instrument:
        activity["instrument"] = instrument

    idem = _cell(row, "idempotency_key")
    if idem:
        activity["idempotency_key"] = idem

    source_ref = _cell(row, "source_ref")
    if source_ref:
        activity["source_ref"] = source_ref

    return activity


def parse_statement(path: Path) -> dict:
    rows = _read_rows(path)

    holdings: list[dict] = []
    activities: list[dict] = []
    for row in rows:
        record_type = (row.get("record_type") or "holding").strip().lower()
        if record_type == "activity":
            activities.append(_to_activity(row))
        else:
            holdings.append(_to_holding(row))

    payload: dict = {
        "provider": "csv-generic",
        "generated_at": _now_iso(),
    }
    if holdings:
        payload["holdings"] = holdings
    if activities:
        payload["activities"] = activities
    if not holdings and not activities:
        payload["holdings"] = []
    return payload


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <statement.csv>", file=sys.stderr)
        return 1

    payload = parse_statement(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
