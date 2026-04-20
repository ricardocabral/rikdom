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
    # Required CSV columns: id,asset_type_id,label,amount,currency
    # Optional: quantity,ticker,country,fx_rate_to_base
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



def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <statement.csv>", file=sys.stderr)
        return 1

    in_path = Path(sys.argv[1])
    rows = _read_rows(in_path)
    holdings = [_to_holding(r) for r in rows]

    payload = {
        "provider": "csv-generic",
        "generated_at": _now_iso(),
        "holdings": holdings,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
