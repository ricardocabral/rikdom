#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from rikdom.import_normalization import (
    normalize_currency,
    normalize_datetime,
    parse_decimal,
)

PROVIDER = "vanguard"
_DEFAULT_CURRENCY = "USD"
_MAX_OFX_BYTES = 32 * 1024 * 1024


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
            raise ValueError("Vanguard CSV is missing header row")
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
        raise ValueError(f"Vanguard {context} row missing required field '{field}'")
    return value


def _stable_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:16]


def _normalize_vanguard_date(value: str) -> str | None:
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


def _normalize_ofx_datetime(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None

    normalized = normalize_datetime(raw)
    if normalized:
        return normalized

    compact = re.sub(r"\[.*\]$", "", raw)
    compact = compact.split(".", 1)[0]
    compact = compact.strip()

    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(compact, fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue

    return None


def _activity_type(action: str) -> tuple[str, str | None]:
    lowered = action.lower()
    if any(token in lowered for token in ("buy", "purchase", "reinvest")):
        return "buy", None
    if any(token in lowered for token in ("sell", "redemption")):
        return "sell", None
    if "dividend" in lowered:
        return "dividend", None
    if "interest" in lowered:
        return "interest", None
    if any(token in lowered for token in ("fee", "expense", "advisory")):
        return "fee", None
    if any(token in lowered for token in ("transfer in", "deposit", "incoming")):
        return "transfer_in", None
    if any(token in lowered for token in ("transfer out", "withdraw", "outgoing")):
        return "transfer_out", None
    return "other", f"vanguard:{_slug(action)}"


def _normalize_amount_sign(event_type: str, amount: float) -> float:
    if event_type in {"buy", "fee", "transfer_out"}:
        return -abs(amount)
    if event_type in {"sell", "dividend", "interest", "transfer_in"}:
        return abs(amount)
    return amount


def _asset_type_for_security(security_type: str, symbol: str) -> str:
    lower_type = security_type.lower()
    if symbol.upper() in {"CASH", "VMFXX", "VUSXX"}:
        return "cash_equivalent"
    if any(token in lower_type for token in ("cash", "money market")):
        return "cash_equivalent"
    if any(token in lower_type for token in ("etf", "fund", "mutual")):
        return "fund"
    if any(token in lower_type for token in ("bond", "fixed income")):
        return "debt_instrument"
    if any(token in lower_type for token in ("stock", "equity")):
        return "stock"
    return "other"


def _parse_position(row: dict[str, str]) -> dict[str, Any]:
    account_number = _required(row, "account_number", context="position")
    symbol = _required(row, "symbol", context="position").upper()
    label = _required(row, "description", context="position")

    quantity = parse_decimal(_required(row, "quantity", context="position"))
    if quantity is None:
        raise ValueError("Vanguard position row has invalid quantity")

    market_value = parse_decimal(_required(row, "market_value", context="position"))
    if market_value is None:
        raise ValueError("Vanguard position row has invalid market_value")

    security_type = row.get("security_type", "")
    currency = normalize_currency(row.get("currency")) or _DEFAULT_CURRENCY

    holding: dict[str, Any] = {
        "id": f"vanguard:{_slug(account_number)}:pos:{_slug(symbol)}",
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
    isin = row.get("isin", "").strip().upper()
    if isin:
        holding["identifiers"]["isin"] = isin
    if security_type:
        holding["metadata"] = {"security_type": security_type}
    return holding


def _parse_cash(row: dict[str, str]) -> dict[str, Any]:
    account_number = _required(row, "account_number", context="cash")
    cash_balance = parse_decimal(_required(row, "cash_balance", context="cash"))
    if cash_balance is None:
        raise ValueError("Vanguard cash row has invalid cash_balance")

    currency = normalize_currency(row.get("currency")) or _DEFAULT_CURRENCY
    return {
        "id": f"vanguard:{_slug(account_number)}:cash:{currency.lower()}",
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
    action = _required(row, "activity_type", context="transaction")
    raw_amount = _required(row, "amount", context="transaction")

    amount = parse_decimal(raw_amount)
    if amount is None:
        raise ValueError("Vanguard transaction row has invalid amount")

    event_type, subtype = _activity_type(action)
    amount = _normalize_amount_sign(event_type, amount)

    raw_date = _required(row, "date", context="transaction")
    effective_at = _normalize_vanguard_date(raw_date)
    if not effective_at:
        raise ValueError(f"Vanguard transaction row has invalid date '{raw_date}'")

    currency = normalize_currency(row.get("currency")) or _DEFAULT_CURRENCY
    symbol = row.get("symbol", "").upper()
    quantity = parse_decimal(row.get("quantity"))
    fees = parse_decimal(row.get("fees"))

    reference_id = row.get("reference_id", "").strip()
    fingerprint = {
        "account_number": account_number,
        "date": effective_at,
        "activity_type": action,
        "symbol": symbol,
        "amount": amount,
        "quantity": quantity,
        "reference_id": reference_id,
    }
    digest = _stable_digest(fingerprint)
    tx_ref = reference_id or digest

    activity: dict[str, Any] = {
        "id": f"vanguard-txn-{_slug(account_number)}-{tx_ref}",
        "event_type": event_type,
        "status": "posted",
        "effective_at": effective_at,
        "money": {"amount": amount, "currency": currency},
        "idempotency_key": f"vanguard:{_slug(account_number)}:{digest}",
        "source_ref": f"vanguard:{account_number}#txn:{tx_ref}",
        "metadata": {
            "activity_type": action,
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].upper()


def _iter_elements(root: Element, name: str):
    wanted = name.upper()
    for elem in root.iter():
        if _local_name(elem.tag) == wanted:
            yield elem


def _first_text(parent: Element, name: str) -> str:
    for elem in _iter_elements(parent, name):
        raw = (elem.text or "").strip()
        if raw:
            return raw
    return ""


def _close_ofx_sgml_leaf_tags(raw: str) -> str:
    lines = raw.splitlines()
    out: list[str] = []
    leaf_pattern = re.compile(r"^(\s*)<([A-Za-z0-9_.:-]+)>([^<]+?)\s*$")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        if stripped.startswith("<?") or stripped.startswith("<!"):
            out.append(line)
            continue
        match = leaf_pattern.match(line)
        if match:
            indent, tag, value = match.groups()
            escaped_value = html.escape(value.strip(), quote=False)
            out.append(f"{indent}<{tag}>{escaped_value}</{tag}>")
            continue
        out.append(line)
    return "\n".join(out)


def _load_ofx_root(path: Path) -> Element:
    size = path.stat().st_size
    if size > _MAX_OFX_BYTES:
        raise ValueError(
            f"Vanguard OFX input exceeds {_MAX_OFX_BYTES} bytes (size={size})"
        )

    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("Vanguard OFX input is empty")

    start = raw.upper().find("<OFX")
    body = raw[start:] if start >= 0 else raw
    xml_like = _close_ofx_sgml_leaf_tags(body)

    try:
        return DefusedET.fromstring(xml_like, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise ValueError(f"Unsafe Vanguard OFX rejected: {exc}") from exc
    except ParseError as exc:
        raise ValueError(f"Invalid Vanguard OFX: {exc}") from exc


def _security_type_from_position_tag(tag: str) -> str:
    mapping = {
        "POSSTOCK": "Stock",
        "POSMF": "Mutual Fund",
        "POSDEBT": "Bond",
        "POSOTHER": "Other",
    }
    return mapping.get(tag.upper(), "Other")


def _asset_type_from_position_tag(tag: str) -> str:
    mapping = {
        "POSSTOCK": "stock",
        "POSMF": "fund",
        "POSDEBT": "debt_instrument",
        "POSOTHER": "other",
    }
    return mapping.get(tag.upper(), "other")


def _parse_ofx_securities(root: Element) -> dict[str, dict[str, str]]:
    securities: dict[str, dict[str, str]] = {}
    for info in _iter_elements(root, "SECINFO"):
        unique_id = _first_text(info, "UNIQUEID")
        if not unique_id:
            continue
        securities[unique_id] = {
            "ticker": _first_text(info, "TICKER").upper(),
            "name": _first_text(info, "SECNAME"),
            "unique_id_type": _first_text(info, "UNIQUEIDTYPE").upper(),
        }
    return securities


def _parse_ofx_position(
    position: Element,
    *,
    account_number: str,
    currency: str,
    securities: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    position_tag = _local_name(position.tag)
    unique_id = _first_text(position, "UNIQUEID")
    quantity = parse_decimal(_first_text(position, "UNITS"))
    market_value = parse_decimal(_first_text(position, "MKTVAL"))
    unit_price = parse_decimal(_first_text(position, "UNITPRICE"))

    if quantity is None:
        return None
    if market_value is None and unit_price is not None:
        market_value = quantity * unit_price
    if market_value is None:
        return None

    sec = securities.get(unique_id, {})
    ticker = sec.get("ticker") or unique_id or "UNKNOWN"
    label = sec.get("name") or ticker

    holding: dict[str, Any] = {
        "id": f"vanguard:{_slug(account_number)}:pos:{_slug(ticker)}",
        "asset_type_id": _asset_type_from_position_tag(position_tag),
        "label": label,
        "quantity": quantity,
        "market_value": {"amount": market_value, "currency": currency},
        "identifiers": {
            "ticker": ticker,
            "provider_account_id": account_number,
        },
        "jurisdiction": {"country": "US"},
        "metadata": {"security_type": _security_type_from_position_tag(position_tag)},
    }

    unique_id_type = sec.get("unique_id_type", "")
    if unique_id and unique_id_type == "ISIN":
        holding["identifiers"]["isin"] = unique_id

    return holding


def _parse_ofx_trade_activity(
    tx: Element,
    *,
    account_number: str,
    currency: str,
    securities: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    tag = _local_name(tx.tag)
    if tag.startswith("BUY"):
        event_type = "buy"
        action_label = "Buy"
    elif tag.startswith("SELL"):
        event_type = "sell"
        action_label = "Sell"
    else:
        return None

    invtran = next(_iter_elements(tx, "INVTRAN"), None)
    if invtran is None:
        return None

    fitid = _first_text(invtran, "FITID")
    traded_at = _normalize_ofx_datetime(_first_text(invtran, "DTTRADE"))
    if not traded_at:
        return None

    sec_id = _first_text(tx, "UNIQUEID")
    sec = securities.get(sec_id, {})
    ticker = (sec.get("ticker") or sec_id).upper()

    quantity = parse_decimal(_first_text(tx, "UNITS"))
    total = parse_decimal(_first_text(tx, "TOTAL"))
    if total is None:
        return None
    total = _normalize_amount_sign(event_type, total)

    commission = parse_decimal(_first_text(tx, "COMMISSION"))

    fingerprint = {
        "account_number": account_number,
        "effective_at": traded_at,
        "event_type": event_type,
        "ticker": ticker,
        "amount": total,
        "quantity": quantity,
        "fitid": fitid,
    }
    digest = _stable_digest(fingerprint)
    tx_ref = fitid or digest

    activity: dict[str, Any] = {
        "id": f"vanguard-txn-{_slug(account_number)}-{tx_ref}",
        "event_type": event_type,
        "status": "posted",
        "effective_at": traded_at,
        "money": {"amount": total, "currency": currency},
        "idempotency_key": f"vanguard:{_slug(account_number)}:{digest}",
        "source_ref": f"vanguard:{account_number}#txn:{tx_ref}",
        "metadata": {
            "activity_type": action_label,
            "description": sec.get("name") or ticker,
            "input_format": "ofx",
        },
    }

    if ticker and ticker not in {"CASH", "USD"}:
        activity["instrument"] = {"ticker": ticker, "country": "US"}

    if quantity is not None and quantity != 0:
        activity["quantity"] = abs(quantity)

    if commission is not None and commission != 0:
        activity["fees"] = {"amount": abs(commission), "currency": currency}

    return activity


def _parse_ofx_income_activity(
    tx: Element,
    *,
    account_number: str,
    currency: str,
    securities: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    invtran = next(_iter_elements(tx, "INVTRAN"), None)
    if invtran is None:
        return None

    fitid = _first_text(invtran, "FITID")
    effective_at = _normalize_ofx_datetime(_first_text(invtran, "DTTRADE"))
    if not effective_at:
        effective_at = _normalize_ofx_datetime(_first_text(invtran, "DTSETTLE"))
    if not effective_at:
        return None

    amount = parse_decimal(_first_text(tx, "TOTAL"))
    if amount is None:
        return None

    income_type = _first_text(tx, "INCOMETYPE").upper()
    if income_type == "DIV":
        event_type = "dividend"
        action_label = "Dividend"
    elif income_type == "INTEREST":
        event_type = "interest"
        action_label = "Interest"
    else:
        event_type = "other"
        action_label = income_type or "Income"

    sec_id = _first_text(tx, "UNIQUEID")
    sec = securities.get(sec_id, {})
    ticker = (sec.get("ticker") or sec_id).upper()

    fingerprint = {
        "account_number": account_number,
        "effective_at": effective_at,
        "event_type": event_type,
        "ticker": ticker,
        "amount": abs(amount),
        "fitid": fitid,
    }
    digest = _stable_digest(fingerprint)
    tx_ref = fitid or digest

    activity: dict[str, Any] = {
        "id": f"vanguard-txn-{_slug(account_number)}-{tx_ref}",
        "event_type": event_type,
        "status": "posted",
        "effective_at": effective_at,
        "money": {"amount": abs(amount), "currency": currency},
        "idempotency_key": f"vanguard:{_slug(account_number)}:{digest}",
        "source_ref": f"vanguard:{account_number}#txn:{tx_ref}",
        "metadata": {
            "activity_type": action_label,
            "description": sec.get("name") or ticker or "",
            "input_format": "ofx",
        },
    }

    if event_type == "other" and income_type:
        activity["subtype"] = f"vanguard:{_slug(income_type)}"

    if ticker and ticker not in {"CASH", "USD"}:
        activity["instrument"] = {"ticker": ticker, "country": "US"}

    return activity


def _parse_ofx_expense_activity(
    tx: Element,
    *,
    account_number: str,
    currency: str,
) -> dict[str, Any] | None:
    invtran = next(_iter_elements(tx, "INVTRAN"), None)
    if invtran is None:
        return None

    fitid = _first_text(invtran, "FITID")
    effective_at = _normalize_ofx_datetime(_first_text(invtran, "DTTRADE"))
    if not effective_at:
        return None

    amount = parse_decimal(_first_text(tx, "TOTAL"))
    if amount is None:
        return None

    memo = _first_text(tx, "MEMO")
    fee_amount = -abs(amount)

    fingerprint = {
        "account_number": account_number,
        "effective_at": effective_at,
        "event_type": "fee",
        "amount": fee_amount,
        "fitid": fitid,
    }
    digest = _stable_digest(fingerprint)
    tx_ref = fitid or digest

    return {
        "id": f"vanguard-txn-{_slug(account_number)}-{tx_ref}",
        "event_type": "fee",
        "status": "posted",
        "effective_at": effective_at,
        "money": {"amount": fee_amount, "currency": currency},
        "idempotency_key": f"vanguard:{_slug(account_number)}:{digest}",
        "source_ref": f"vanguard:{account_number}#txn:{tx_ref}",
        "metadata": {
            "activity_type": "Fee",
            "description": memo,
            "input_format": "ofx",
        },
    }


def _parse_ofx_statement(path: Path) -> dict[str, Any]:
    root = _load_ofx_root(path)

    account_number = _first_text(root, "ACCTID") or "unknown-account"
    currency = normalize_currency(_first_text(root, "CURDEF")) or _DEFAULT_CURRENCY
    generated_at = (
        _normalize_ofx_datetime(_first_text(root, "DTSERVER"))
        or _normalize_ofx_datetime(_first_text(root, "DTASOF"))
        or _normalize_ofx_datetime(_first_text(root, "DTEND"))
        or _now_iso()
    )

    account_type = _first_text(root, "ACCTTYPE")
    broker_id = _first_text(root, "BROKERID")
    securities = _parse_ofx_securities(root)

    holdings: list[dict[str, Any]] = []
    seen_holding_ids: set[str] = set()
    for position_tag in ("POSSTOCK", "POSMF", "POSDEBT", "POSOTHER"):
        for position in _iter_elements(root, position_tag):
            holding = _parse_ofx_position(
                position,
                account_number=account_number,
                currency=currency,
                securities=securities,
            )
            if holding is None:
                continue
            hid = holding["id"]
            if hid in seen_holding_ids:
                continue
            seen_holding_ids.add(hid)
            holdings.append(holding)

    available_cash = parse_decimal(_first_text(root, "AVAILCASH"))
    if available_cash is not None:
        cash_holding = {
            "id": f"vanguard:{_slug(account_number)}:cash:{currency.lower()}",
            "asset_type_id": "cash_equivalent",
            "label": f"Cash balance ({currency})",
            "market_value": {"amount": available_cash, "currency": currency},
            "identifiers": {
                "provider_account_id": account_number,
                "ticker": "CASH",
            },
            "jurisdiction": {"country": "US"},
        }
        if cash_holding["id"] not in seen_holding_ids:
            holdings.append(cash_holding)
            seen_holding_ids.add(cash_holding["id"])

    activities: list[dict[str, Any]] = []
    seen_activity_ids: set[str] = set()

    for tag in ("BUYMF", "BUYSTOCK", "BUYOTHER", "SELLMF", "SELLSTOCK", "SELLOTHER"):
        for tx in _iter_elements(root, tag):
            activity = _parse_ofx_trade_activity(
                tx,
                account_number=account_number,
                currency=currency,
                securities=securities,
            )
            if activity is None:
                continue
            aid = activity["id"]
            if aid in seen_activity_ids:
                continue
            activities.append(activity)
            seen_activity_ids.add(aid)

    for tx in _iter_elements(root, "INCOME"):
        activity = _parse_ofx_income_activity(
            tx,
            account_number=account_number,
            currency=currency,
            securities=securities,
        )
        if activity is None:
            continue
        aid = activity["id"]
        if aid in seen_activity_ids:
            continue
        activities.append(activity)
        seen_activity_ids.add(aid)

    for tx in _iter_elements(root, "INVEXPENSE"):
        activity = _parse_ofx_expense_activity(
            tx,
            account_number=account_number,
            currency=currency,
        )
        if activity is None:
            continue
        aid = activity["id"]
        if aid in seen_activity_ids:
            continue
        activities.append(activity)
        seen_activity_ids.add(aid)

    if not holdings and not activities:
        raise ValueError("Vanguard OFX did not contain usable holdings or activities")

    metadata: dict[str, Any] = {
        "source_file": path.name,
        "input_format": "ofx",
        "accounts": [
            {
                "account_number": account_number,
                "currency": currency,
                **({"account_type": account_type} if account_type else {}),
                **({"broker_id": broker_id} if broker_id else {}),
            }
        ],
    }

    return {
        "provider": PROVIDER,
        "generated_at": generated_at,
        "base_currency": currency,
        "metadata": metadata,
        **({"holdings": holdings} if holdings else {}),
        **({"activities": activities} if activities else {}),
    }


def _parse_csv_statement(path: Path) -> dict[str, Any]:
    rows = _read_rows(path)
    if not rows:
        raise ValueError("Vanguard CSV contains no rows")

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
        account_type = row.get("account_type", "").strip()
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
            if account_type:
                info["account_type"] = account_type

        statement_date = _normalize_vanguard_date(row.get("statement_date", ""))
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
            "Vanguard row has unknown record_type; expected one of "
            "account, position, cash, transaction"
        )

    if not holdings and not activities:
        raise ValueError("Vanguard CSV did not produce holdings or activities")

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


def parse_statement(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"input file does not exist: {path}")

    suffix = path.suffix.lower()
    if suffix in {".ofx", ".qfx"}:
        return _parse_ofx_statement(path)
    return _parse_csv_statement(path)


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: importer.py <vanguard-statement.csv|vanguard-statement.ofx>",
            file=sys.stderr,
        )
        return 1

    payload = parse_statement(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
