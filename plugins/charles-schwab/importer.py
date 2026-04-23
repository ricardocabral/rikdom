#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rikdom.import_normalization import (
    normalize_currency,
    normalize_datetime,
    parse_decimal,
)

PROVIDER = "charles-schwab"
_DEFAULT_CURRENCY = "USD"


def _now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "unknown"


def _norm_header(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_{2,}", "_", normalized).strip("_")
    return normalized


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("Charles Schwab CSV is missing header row")
        rows: list[dict[str, str]] = []
        for raw in reader:
            normalized_row: dict[str, str] = {}
            for key, value in raw.items():
                if key is None:
                    continue
                normalized_row[_norm_header(key)] = (value or "").strip()
            if any(v for v in normalized_row.values()):
                rows.append(normalized_row)
        return rows


def _required(row: dict[str, str], field: str, *, context: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(
            f"Charles Schwab {context} row missing required field '{field}'"
        )
    return value


def _stable_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:16]


def _normalize_schwab_date(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None

    for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue

    return normalize_datetime(raw)


def _activity_type(action: str) -> tuple[str, str | None]:
    lowered = action.lower()
    if "buy" in lowered:
        return "buy", None
    if "sell" in lowered:
        return "sell", None
    if "dividend" in lowered:
        return "dividend", None
    if "interest" in lowered:
        return "interest", None
    if "fee" in lowered or "commission" in lowered:
        return "fee", None
    if any(
        token in lowered
        for token in ("transfer in", "deposit", "wire received", "incoming")
    ):
        return "transfer_in", None
    if any(
        token in lowered
        for token in ("transfer out", "withdraw", "wire sent", "outgoing")
    ):
        return "transfer_out", None
    return "other", f"schwab:{_slug(action)}"


def _normalize_amount_sign(event_type: str, amount: float) -> float:
    if event_type in {"buy", "fee", "transfer_out"}:
        return -abs(amount)
    if event_type in {"sell", "dividend", "interest", "transfer_in"}:
        return abs(amount)
    return amount


def _asset_type_for_security(security_type: str, symbol: str) -> str:
    lower_type = security_type.lower()
    if symbol.upper() in {"CASH", "SWVXX"}:
        return "cash_equivalent"
    if "cash" in lower_type or "money market" in lower_type:
        return "cash_equivalent"
    if "etf" in lower_type or "fund" in lower_type or "mutual" in lower_type:
        return "fund"
    if "bond" in lower_type or "fixed income" in lower_type:
        return "debt_instrument"
    if "stock" in lower_type or "equity" in lower_type:
        return "stock"
    return "other"


def _parse_position(row: dict[str, str]) -> dict[str, Any]:
    account_number = _required(row, "account_number", context="position")
    symbol = _required(row, "symbol", context="position").upper()
    label = _required(row, "description", context="position")

    quantity = parse_decimal(_required(row, "quantity", context="position"))
    if quantity is None:
        raise ValueError("Charles Schwab position row has invalid quantity")

    market_value = parse_decimal(_required(row, "market_value", context="position"))
    if market_value is None:
        raise ValueError("Charles Schwab position row has invalid market_value")

    security_type = row.get("security_type", "")
    currency = normalize_currency(row.get("currency")) or _DEFAULT_CURRENCY

    holding: dict[str, Any] = {
        "id": f"schwab:{_slug(account_number)}:pos:{_slug(symbol)}",
        "asset_type_id": _asset_type_for_security(security_type, symbol),
        "label": label,
        "quantity": quantity,
        "market_value": {"amount": market_value, "currency": currency},
        "identifiers": {
            "ticker": symbol,
            "provider_account_id": account_number,
        },
        "jurisdiction": {"country": "US"},
    }
    if security_type:
        holding["metadata"] = {"security_type": security_type}
    return holding


def _parse_cash(row: dict[str, str]) -> dict[str, Any]:
    account_number = _required(row, "account_number", context="cash")
    cash_balance = parse_decimal(_required(row, "cash_balance", context="cash"))
    if cash_balance is None:
        raise ValueError("Charles Schwab cash row has invalid cash_balance")

    currency = normalize_currency(row.get("currency")) or _DEFAULT_CURRENCY
    return {
        "id": f"schwab:{_slug(account_number)}:cash:{currency.lower()}",
        "asset_type_id": "cash_equivalent",
        "label": f"Cash balance ({currency})",
        "market_value": {"amount": cash_balance, "currency": currency},
        "identifiers": {
            "provider_account_id": account_number,
            "ticker": "CASH",
        },
        "jurisdiction": {"country": "US"},
    }


def _parse_transaction(row: dict[str, str]) -> dict[str, Any]:
    account_number = _required(row, "account_number", context="transaction")
    action = _required(row, "action", context="transaction")
    raw_amount = _required(row, "amount", context="transaction")

    amount = parse_decimal(raw_amount)
    if amount is None:
        raise ValueError("Charles Schwab transaction row has invalid amount")

    event_type, subtype = _activity_type(action)
    amount = _normalize_amount_sign(event_type, amount)

    raw_date = _required(row, "date", context="transaction")
    effective_at = _normalize_schwab_date(raw_date)
    if not effective_at:
        raise ValueError(
            f"Charles Schwab transaction row has invalid date '{raw_date}'"
        )

    currency = normalize_currency(row.get("currency")) or _DEFAULT_CURRENCY
    symbol = row.get("symbol", "").upper()
    quantity = parse_decimal(row.get("quantity"))
    fees = parse_decimal(row.get("fees"))

    reference_id = row.get("reference_id", "").strip()
    fingerprint = {
        "account_number": account_number,
        "date": effective_at,
        "action": action,
        "symbol": symbol,
        "amount": amount,
        "quantity": quantity,
        "reference_id": reference_id,
    }
    digest = _stable_digest(fingerprint)
    tx_ref = reference_id or digest

    activity: dict[str, Any] = {
        "id": f"schwab-txn-{_slug(account_number)}-{tx_ref}",
        "event_type": event_type,
        "status": "posted",
        "effective_at": effective_at,
        "money": {"amount": amount, "currency": currency},
        "idempotency_key": f"schwab:{_slug(account_number)}:{digest}",
        "source_ref": f"schwab:{account_number}#txn:{tx_ref}",
        "metadata": {
            "action": action,
            "description": row.get("description", ""),
        },
    }

    if subtype:
        activity["subtype"] = subtype

    if symbol and symbol not in {"CASH", "USD"}:
        activity["instrument"] = {"ticker": symbol, "country": "US"}

    if quantity is not None and quantity != 0:
        activity["quantity"] = abs(quantity)

    if fees is not None and fees != 0:
        activity["fees"] = {"amount": abs(fees), "currency": currency}

    return activity


def parse_statement(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"input file does not exist: {path}")

    rows = _read_rows(path)
    if not rows:
        raise ValueError("Charles Schwab CSV contains no rows")

    holdings: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    accounts: dict[str, dict[str, Any]] = {}
    generated_candidates: list[str] = []

    seen_holding_ids: set[str] = set()
    seen_activity_ids: set[str] = set()

    for row in rows:
        record_type = row.get("record_type", "").strip().lower()
        account_number = row.get("account_number", "").strip()
        account_name = row.get("account_name", "").strip()
        currency = normalize_currency(row.get("currency")) or _DEFAULT_CURRENCY

        if account_number:
            info = accounts.setdefault(
                account_number,
                {
                    "account_number": account_number,
                    "currency": currency,
                },
            )
            if account_name:
                info["account_name"] = account_name

        statement_date = _normalize_schwab_date(row.get("statement_date", ""))
        if statement_date:
            generated_candidates.append(statement_date)

        if record_type == "account":
            continue
        if record_type == "position":
            holding = _parse_position(row)
            if holding["id"] not in seen_holding_ids:
                holdings.append(holding)
                seen_holding_ids.add(holding["id"])
            continue
        if record_type == "cash":
            holding = _parse_cash(row)
            if holding["id"] not in seen_holding_ids:
                holdings.append(holding)
                seen_holding_ids.add(holding["id"])
            continue
        if record_type == "transaction":
            activity = _parse_transaction(row)
            if activity["id"] not in seen_activity_ids:
                activities.append(activity)
                seen_activity_ids.add(activity["id"])
            continue

        raise ValueError(
            "Charles Schwab row has unknown record_type; expected one of "
            "account, position, cash, transaction"
        )

    if not holdings and not activities:
        raise ValueError("Charles Schwab CSV did not produce holdings or activities")

    metadata: dict[str, Any] = {
        "source_file": path.name,
        "accounts": sorted(accounts.values(), key=lambda item: item["account_number"]),
    }

    generated_at = max(generated_candidates) if generated_candidates else _now_iso()
    return {
        "provider": PROVIDER,
        "generated_at": generated_at,
        "base_currency": "USD",
        "metadata": metadata,
        **({"holdings": holdings} if holdings else {}),
        **({"activities": activities} if activities else {}),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <schwab-statement.csv>", file=sys.stderr)
        return 1

    payload = parse_statement(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
