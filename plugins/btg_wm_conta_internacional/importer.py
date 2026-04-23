#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVIDER = "btg_wm_conta_internacional"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _parse_signed_number(value: str) -> float:
    raw = _collapse_spaces(value)
    if not raw:
        raise ValueError("cannot parse empty numeric value")
    negative = raw.startswith("(") and raw.endswith(")")
    compact = raw.strip("()$").replace(",", "")
    try:
        amount = float(compact)
    except ValueError as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc
    return -amount if negative else amount


def _parse_mmddyyyy_to_iso(value: str) -> str:
    dt = datetime.strptime(value, "%m/%d/%Y")
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "unknown"


def _extract_text(input_path: Path) -> str:
    if input_path.suffix.lower() == ".txt":
        return input_path.read_text(encoding="utf-8")

    if input_path.suffix.lower() != ".pdf":
        raise ValueError("BTG WM importer expects a .pdf statement (or .txt extracted text fixture)")

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(input_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "pdftotext is required to parse BTG WM PDF statements; install poppler"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise ValueError(f"failed to extract text from PDF: {stderr or exc}") from exc

    text = result.stdout
    if not text.strip():
        raise ValueError("PDF text extraction produced empty output")
    return text


def _extract_account_number(text: str) -> str:
    m = re.search(r"Account Number:\s*([A-Z0-9\-]+)", text)
    return m.group(1) if m else "unknown-account"


def _extract_statement_period(text: str) -> tuple[str | None, str | None]:
    m = re.search(
        r"([A-Za-z]+\s+\d{2},\s+\d{4})\s*-\s*([A-Za-z]+\s+\d{2},\s+\d{4})",
        text,
    )
    if not m:
        return None, None

    start = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    end = datetime.strptime(m.group(2), "%B %d, %Y").date().isoformat()
    return start, end


def _extract_ending_account_value(text: str) -> float | None:
    m = re.search(r"Ending Account Value\s+\$?([0-9,]+\.\d{2})", text)
    if not m:
        return None
    return _parse_signed_number(m.group(1))


def _section(text: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    start = text.find(start_marker)
    if start < 0:
        return ""
    end = len(text)
    for marker in end_markers:
        idx = text.find(marker, start + len(start_marker))
        if idx >= 0:
            end = min(end, idx)
    return text[start:end]


_HOLDING_ROW_RE = re.compile(
    r"^(?P<description>.+?)\s{2,}"
    r"(?P<symbol>[A-Z0-9.\-]+)\s+"
    r"(?P<quantity>[\d,]+(?:\.\d+)?)\s+"
    r"(?P<unit_cost>\(?[\d,]+\.\d+\)?)\s+"
    r"(?P<total_cost>\(?[\d,]+\.\d+\)?)\s+"
    r"(?P<market_price>\(?[\d,]+\.\d+\)?)\s+"
    r"(?P<market_value>\(?[\d,]+\.\d+\)?)\s+"
    r"(?P<gain_loss>\(?[\d,]+\.\d+\)?)\s+"
    r"(?P<account_type>[A-Z])$"
)


def _asset_type_for_bucket(bucket: str) -> str:
    normalized = bucket.lower()
    if normalized.startswith("moneymarket"):
        return "cash_equivalent"
    if normalized.startswith("equity"):
        return "stock"
    if normalized.startswith("fixed income"):
        return "debt_instrument"
    if normalized.startswith("mutual"):
        return "fund"
    return "other"


def _parse_holdings(text: str, account_number: str) -> list[dict[str, Any]]:
    segment = _section(text, "HOLDINGS", ("ACTIVITY",))
    if not segment:
        return []

    holdings: list[dict[str, Any]] = []
    current_bucket = ""
    for raw_line in segment.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in {
            "HOLDINGS",
            "Description",
            "Type",
        }:
            continue
        if stripped.startswith("Description") and "Market Value" in stripped:
            continue
        if stripped in {
            "Equity",
            "Options",
            "Fixed Income",
            "Mutual Funds",
            "Other Assets",
            "MoneyMarket funds",
        }:
            current_bucket = stripped
            continue

        match = _HOLDING_ROW_RE.match(line)
        if not match:
            continue

        gd = match.groupdict()
        symbol = gd["symbol"].upper()
        section = current_bucket or "Unknown"
        holdings.append(
            {
                "id": f"btgwm:{_slug(account_number)}:{_slug(symbol)}",
                "asset_type_id": _asset_type_for_bucket(section),
                "label": _collapse_spaces(gd["description"]),
                "quantity": _parse_signed_number(gd["quantity"]),
                "market_value": {
                    "amount": _parse_signed_number(gd["market_value"]),
                    "currency": "USD",
                },
                "identifiers": {
                    "ticker": symbol,
                    "provider_account_id": account_number,
                },
                "jurisdiction": {"country": "US"},
                "metadata": {
                    "provider": "btg-wm-conta-internacional",
                    "holding_bucket": section,
                    "unit_cost": _parse_signed_number(gd["unit_cost"]),
                    "total_cost": _parse_signed_number(gd["total_cost"]),
                    "market_price": _parse_signed_number(gd["market_price"]),
                    "gain_loss": _parse_signed_number(gd["gain_loss"]),
                    "account_type": gd["account_type"],
                },
            }
        )

    return holdings


_ACTIVITY_PREFIX_RE = re.compile(
    r"^(?P<trade_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<settle_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<currency>[A-Z]{3})\s+"
    r"(?P<activity_type>[A-Z0-9]+)\s+"
    r"(?P<tail>.+)$"
)

_ACTIVITY_TAIL_RE = re.compile(
    r"^(?P<description>.+?)\s+"
    r"(?P<quantity>[\d,]+(?:\.\d+)?)\s+"
    r"(?P<price>\(?[\d,]+\.\d+\)?)\s+"
    r"(?P<amount>\(?[\d,]+\.\d+\)?)$"
)


def _normalize_event_type(activity_type: str, description: str) -> tuple[str, str | None]:
    kind = activity_type.upper()
    if kind == "DIV":
        return "dividend", None
    if kind == "DIVNRA":
        return "fee", "withholding_tax"
    if kind == "BUY":
        return "buy", None
    if kind == "SELL":
        return "sell", None
    if "FEE" in description.upper():
        return "fee", None
    return "other", f"btg:{kind.lower()}"


def _collect_activity_lines(segment: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for raw_line in segment.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("ACTIVITY") or stripped.startswith("SWEEP ACTIVITY"):
            continue
        if stripped.startswith("Trade Date"):
            continue

        prefix = _ACTIVITY_PREFIX_RE.match(stripped)
        if prefix:
            if current is not None:
                rows.append(current)
            current = prefix.groupdict()
            continue

        if current is not None:
            current_tail = _collapse_spaces(current["tail"])
            if _ACTIVITY_TAIL_RE.match(current_tail):
                continue
            current["tail"] = f"{current['tail']} {_collapse_spaces(stripped)}"

    if current is not None:
        rows.append(current)

    return rows


def _parse_activity_table(
    segment: str,
    *,
    account_number: str,
    source_block: str,
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    activities: list[dict[str, Any]] = []
    idx = start_index

    for row in _collect_activity_lines(segment):
        detail = _ACTIVITY_TAIL_RE.match(_collapse_spaces(row["tail"]))
        if not detail:
            continue

        info = detail.groupdict()
        description = _collapse_spaces(info["description"])
        symbol = description.split(" - ", 1)[0].strip().upper()
        event_type, subtype = _normalize_event_type(row["activity_type"], description)
        effective_at = _parse_mmddyyyy_to_iso(row["trade_date"])
        settle_at = _parse_mmddyyyy_to_iso(row["settle_date"])

        digest_source = "|".join(
            [
                account_number,
                source_block,
                row["trade_date"],
                row["activity_type"],
                description,
                info["amount"],
            ]
        )
        digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:14]

        activity: dict[str, Any] = {
            "id": f"btgwm-act-{digest}",
            "event_type": event_type,
            "status": "posted",
            "effective_at": effective_at,
            "money": {
                "amount": _parse_signed_number(info["amount"]),
                "currency": row["currency"],
            },
            "quantity": _parse_signed_number(info["quantity"]),
            "instrument": {"ticker": symbol, "country": "US"},
            "source_ref": f"btgwm:{account_number}#{source_block}:{idx}",
            "metadata": {
                "provider": "btg-wm-conta-internacional",
                "activity_type": row["activity_type"],
                "description": description,
                "price": _parse_signed_number(info["price"]),
                "settle_at": settle_at,
                "source_block": source_block,
            },
        }
        if symbol == "DWBDS":
            activity["asset_type_id"] = "cash_equivalent"
        else:
            activity["asset_type_id"] = "stock"

        if subtype:
            activity["subtype"] = subtype

        activities.append(activity)
        idx += 1

    return activities, idx


def _parse_activities(text: str, account_number: str) -> list[dict[str, Any]]:
    activity_segment = _section(text, "ACTIVITY", ("SWEEP ACTIVITY",))
    sweep_segment = _section(text, "SWEEP ACTIVITY", ("CURRENT MONTH AGGREGATE INTEREST ACCRUED",))

    activities: list[dict[str, Any]] = []
    next_index = 1
    parsed, next_index = _parse_activity_table(
        activity_segment,
        account_number=account_number,
        source_block="activity",
        start_index=next_index,
    )
    activities.extend(parsed)

    parsed, next_index = _parse_activity_table(
        sweep_segment,
        account_number=account_number,
        source_block="sweep_activity",
        start_index=next_index,
    )
    activities.extend(parsed)
    return activities


def parse_statement(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"input file does not exist: {path}")

    text = _extract_text(path)
    account_number = _extract_account_number(text)
    period_start, period_end = _extract_statement_period(text)
    ending_account_value = _extract_ending_account_value(text)

    holdings = _parse_holdings(text, account_number)
    activities = _parse_activities(text, account_number)

    if not holdings and not activities:
        raise ValueError("BTG WM statement did not produce holdings or activities")

    holdings_total = sum(float(h["market_value"]["amount"]) for h in holdings)
    if ending_account_value is not None and holdings:
        if abs(holdings_total - ending_account_value) > 0.05:
            raise ValueError(
                "BTG WM statement total mismatch: "
                f"holdings_total={holdings_total:.2f} vs ending_account_value={ending_account_value:.2f}"
            )

    generated_at = _now_iso()
    if period_end is not None:
        generated_at = f"{period_end}T00:00:00Z"

    metadata: dict[str, Any] = {
        "source_file": path.name,
        "account_number": account_number,
    }
    if period_start is not None:
        metadata["statement_period_start"] = period_start
    if period_end is not None:
        metadata["statement_period_end"] = period_end
    if ending_account_value is not None:
        metadata["ending_account_value"] = ending_account_value
        metadata["parsed_holdings_total"] = round(holdings_total, 2)

    payload: dict[str, Any] = {
        "provider": PROVIDER,
        "generated_at": generated_at,
        "base_currency": "USD",
        "metadata": metadata,
    }
    if holdings:
        payload["holdings"] = holdings
    if activities:
        payload["activities"] = activities
    return payload


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <statement.pdf|statement.txt>", file=sys.stderr)
        return 1

    payload = parse_statement(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
