#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as DefusedET

from rikdom.import_normalization import as_text, normalize_currency, normalize_datetime, parse_decimal

PROVIDER = "ibkr_flex_xml"
MAX_XML_BYTES = 64 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_xml(path: Path) -> Element:
    size = path.stat().st_size
    if size > MAX_XML_BYTES:
        raise ValueError(
            f"IBKR Flex XML input exceeds {MAX_XML_BYTES} bytes (size={size})"
        )
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("IBKR Flex XML input is empty")

    try:
        return DefusedET.fromstring(raw, forbid_dtd=True)
    except ParseError as exc:
        raise ValueError(f"Invalid IBKR Flex XML: {exc}") from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_elements(root: Element, name: str):
    for elem in root.iter():
        if _local_name(elem.tag) == name:
            yield elem


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:16]}"


def _normalize_ibkr_datetime(value: Any) -> str | None:
    raw = as_text(value)
    if not raw:
        return None

    normalized = normalize_datetime(raw)
    if normalized:
        return normalized

    compact = raw.strip()
    parse_formats = (
        "%Y%m%d;%H%M%S",
        "%Y%m%d;%H:%M:%S",
        "%Y%m%d,%H%M%S",
        "%Y%m%d,%H:%M:%S",
        "%Y%m%d %H%M%S",
        "%Y%m%d %H:%M:%S",
        "%Y-%m-%d;%H:%M:%S",
        "%Y-%m-%d,%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d",
    )
    for fmt in parse_formats:
        try:
            dt = datetime.strptime(compact, fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue

    return None


def _resolve_effective_at(row: dict[str, str], *, kind: str, row_id: str) -> str:
    primary_candidates = (
        row.get("dateTime"),
        row.get("tradeDateTime"),
        row.get("dateTimeUTC"),
        row.get("reportDate"),
        row.get("date"),
    )
    for candidate in primary_candidates:
        effective = _normalize_ibkr_datetime(candidate)
        if effective:
            return effective

    trade_date = as_text(row.get("tradeDate"))
    trade_time = as_text(row.get("tradeTime"))
    if trade_date and trade_time:
        effective = _normalize_ibkr_datetime(f"{trade_date};{trade_time}")
        if effective:
            return effective

    if trade_date:
        effective = _normalize_ibkr_datetime(trade_date)
        if effective:
            return effective

    raise ValueError(f"IBKR {kind} row '{row_id}' has unparseable date/time fields")


def _statement_account_id(root: Element) -> str:
    for statement in _iter_elements(root, "FlexStatement"):
        account_id = as_text(statement.attrib.get("accountId") or statement.attrib.get("accountCode"))
        if account_id:
            return account_id
    return "unknown-account"


def _generated_at(root: Element) -> str:
    candidate_attrs = (
        "whenGenerated",
        "generatedAt",
        "reportDate",
        "statementDate",
        "toDate",
    )

    for statement in _iter_elements(root, "FlexStatement"):
        for attr in candidate_attrs:
            normalized = _normalize_ibkr_datetime(statement.attrib.get(attr))
            if normalized:
                return normalized

    for attr in candidate_attrs:
        normalized = _normalize_ibkr_datetime(root.attrib.get(attr))
        if normalized:
            return normalized

    return _now_iso()


def _trade_event_type(row: dict[str, str]) -> str:
    buy_sell = as_text(row.get("buySell")).upper()
    if buy_sell.startswith("BUY"):
        return "buy"
    if buy_sell.startswith("SELL"):
        return "sell"
    return "other"


def _cash_event_type(row: dict[str, str]) -> str:
    raw = " ".join((as_text(row.get("type")), as_text(row.get("description")))).lower()
    if "dividend" in raw:
        return "dividend"
    if "interest" in raw:
        return "interest"
    if "tax" in raw or "withholding" in raw:
        return "other"
    if "fee" in raw or "commission" in raw:
        return "fee"
    if "deposit" in raw or "transfer in" in raw or "incoming" in raw:
        return "transfer_in"
    if "withdraw" in raw or "transfer out" in raw or "outgoing" in raw:
        return "transfer_out"
    return "other"


def _is_cancel_like_trade(row: dict[str, str]) -> bool:
    for flag in ("isCancel", "isCancelled", "cancelled"):
        value = as_text(row.get(flag)).lower()
        if value in {"1", "true", "yes", "y"}:
            return True

    for field in ("notes", "description", "transactionType", "buySell", "code"):
        if "cancel" in as_text(row.get(field)).lower():
            return True

    return False


def _trade_id(row: dict[str, str]) -> str:
    for key in ("transactionID", "tradeID", "executionID", "ibExecID", "orderID"):
        value = as_text(row.get(key))
        if value:
            return value
    return _stable_id("ibkr-trade", row)


def _cash_id(row: dict[str, str]) -> str:
    for key in ("transactionID", "id", "clientReference"):
        value = as_text(row.get(key))
        if value:
            return value
    return _stable_id("ibkr-cash", row)


def _trade_activity(row: dict[str, str], account_id: str) -> dict[str, Any]:
    trade_ref = _trade_id(row)
    event_type = _trade_event_type(row)
    effective_at = _resolve_effective_at(row, kind="trade", row_id=trade_ref)

    currency = normalize_currency(row.get("currency"))
    if not currency:
        raise ValueError(f"IBKR trade row '{trade_ref}' has missing/invalid currency")

    amount = parse_decimal(row.get("proceeds") or row.get("netCash"))
    if amount is None:
        quantity = parse_decimal(row.get("quantity"))
        trade_price = parse_decimal(row.get("tradePrice") or row.get("price"))
        if quantity is None or trade_price is None:
            raise ValueError(
                f"IBKR trade row '{trade_ref}' has no numeric proceeds and cannot derive amount"
            )
        gross = abs(quantity) * trade_price
        amount = -gross if event_type == "buy" else gross

    buy_sell_raw = as_text(row.get("buySell"))
    activity: dict[str, Any] = {
        "id": f"ibkr-trade-{trade_ref}",
        "event_type": event_type,
        "effective_at": effective_at,
        "status": "posted",
        "money": {"amount": amount, "currency": currency},
        "source_ref": f"ibkr:{account_id}#trade:{trade_ref}",
        "metadata": {
            "ibkr_row_type": "Trade",
            "buy_sell": buy_sell_raw,
        },
    }
    if event_type == "other" and buy_sell_raw:
        activity["subtype"] = f"ibkr_trade:{buy_sell_raw.lower()}"

    quantity = parse_decimal(row.get("quantity"))
    if quantity is not None:
        activity["quantity"] = abs(quantity)

    fee_amount = parse_decimal(row.get("ibCommission") or row.get("commission"))
    fee_currency = normalize_currency(row.get("ibCommissionCurrency")) or currency
    if fee_amount is not None:
        activity["fees"] = {"amount": abs(fee_amount), "currency": fee_currency}

    instrument: dict[str, Any] = {}
    symbol = as_text(row.get("symbol") or row.get("underlyingSymbol"))
    if symbol:
        instrument["ticker"] = symbol
    isin = as_text(row.get("isin"))
    if isin:
        instrument["isin"] = isin
    cusip = as_text(row.get("cusip"))
    if cusip:
        instrument["cusip"] = cusip
    if instrument:
        activity["instrument"] = instrument

    return activity


def _cash_activity(row: dict[str, str], account_id: str) -> dict[str, Any]:
    cash_ref = _cash_id(row)
    effective_at = _resolve_effective_at(row, kind="cash", row_id=cash_ref)

    currency = normalize_currency(row.get("currency"))
    if not currency:
        raise ValueError(f"IBKR cash row '{cash_ref}' has missing/invalid currency")

    amount = parse_decimal(row.get("amount"))
    if amount is None:
        raise ValueError(f"IBKR cash row '{cash_ref}' has missing/invalid amount")

    event_type = _cash_event_type(row)
    cash_type_raw = as_text(row.get("type"))
    description_raw = as_text(row.get("description"))
    activity: dict[str, Any] = {
        "id": f"ibkr-cash-{cash_ref}",
        "event_type": event_type,
        "effective_at": effective_at,
        "status": "posted",
        "money": {"amount": amount, "currency": currency},
        "source_ref": f"ibkr:{account_id}#cash:{cash_ref}",
        "metadata": {
            "ibkr_row_type": "CashTransaction",
            "cash_type": cash_type_raw,
            "description": description_raw,
        },
    }
    if event_type == "other":
        raw_tag = cash_type_raw or description_raw
        if raw_tag:
            activity["subtype"] = f"ibkr_cash:{raw_tag.lower()[:64]}"

    instrument_symbol = as_text(row.get("symbol"))
    if instrument_symbol:
        activity["instrument"] = {"ticker": instrument_symbol}

    return activity


def parse_statement(path: Path) -> dict[str, Any]:
    root = _load_xml(path)
    account_id = _statement_account_id(root)

    activities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for trade in _iter_elements(root, "Trade"):
        row = {k: v for k, v in trade.attrib.items()}
        if _is_cancel_like_trade(row):
            continue
        activity = _trade_activity(row, account_id)
        aid = activity["id"]
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        activities.append(activity)

    for cash_row in _iter_elements(root, "CashTransaction"):
        row = {k: v for k, v in cash_row.attrib.items()}
        activity = _cash_activity(row, account_id)
        aid = activity["id"]
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        activities.append(activity)

    if not activities:
        raise ValueError("IBKR Flex XML did not contain usable Trade or CashTransaction rows")

    return {
        "provider": PROVIDER,
        "generated_at": _generated_at(root),
        "activities": activities,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <ibkr-flex.xml>", file=sys.stderr)
        return 1

    payload = parse_statement(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
