#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path



def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")



def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]



def _to_holding(row: dict[str, str]) -> dict:
    amount = float(row["amount"])
    holding = {
        "id": row["id"].strip(),
        "asset_type_id": row["asset_type_id"].strip(),
        "label": row["label"].strip(),
        "market_value": {
            "amount": amount,
            "currency": row["currency"].strip().upper(),
        },
    }

    quantity = row.get("quantity", "").strip()
    if quantity:
        holding["quantity"] = float(quantity)

    ticker = row.get("ticker", "").strip()
    if ticker:
        holding["identifiers"] = {"ticker": ticker}

    country = row.get("country", "").strip().upper()
    if country:
        holding["jurisdiction"] = {"country": country}

    fx_rate = row.get("fx_rate_to_base", "").strip()
    if fx_rate:
        holding["metadata"] = {"fx_rate_to_base": float(fx_rate)}

    return holding



def _to_activity(row: dict[str, str]) -> dict:
    amount = float(row["amount"])
    currency = row["currency"].strip().upper()
    event_type = (row.get("event_type") or "").strip() or "other"
    effective_at = (row.get("effective_at") or "").strip() or _now_iso()

    activity: dict = {
        "id": row["id"].strip(),
        "event_type": event_type,
        "status": (row.get("status") or "").strip() or "posted",
        "effective_at": effective_at,
        "money": {"amount": amount, "currency": currency},
    }

    asset_type_id = (row.get("asset_type_id") or "").strip()
    if asset_type_id:
        activity["asset_type_id"] = asset_type_id

    subtype = (row.get("subtype") or "").strip()
    if subtype:
        activity["subtype"] = subtype

    quantity = (row.get("quantity") or "").strip()
    if quantity:
        activity["quantity"] = float(quantity)

    instrument: dict = {}
    ticker = (row.get("ticker") or "").strip()
    if ticker:
        instrument["ticker"] = ticker
    country = (row.get("country") or "").strip().upper()
    if country:
        instrument["country"] = country
    if instrument:
        activity["instrument"] = instrument

    idem = (row.get("idempotency_key") or "").strip()
    if idem:
        activity["idempotency_key"] = idem

    source_ref = (row.get("source_ref") or "").strip()
    if source_ref:
        activity["source_ref"] = source_ref

    return activity



def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <statement.csv>", file=sys.stderr)
        return 1

    in_path = Path(sys.argv[1])
    rows = _read_rows(in_path)

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

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
