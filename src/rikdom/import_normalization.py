from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_currency(value: Any) -> str | None:
    raw = as_text(value).upper()
    if len(raw) != 3 or not raw.isalpha():
        return None
    return raw


def parse_decimal(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    raw = as_text(value)
    if not raw:
        return None

    compact = raw.replace(" ", "")
    compact = compact.replace("R$", "").replace("$", "")
    if "," in compact and "." in compact:
        if compact.rfind(",") > compact.rfind("."):
            compact = compact.replace(".", "")
            compact = compact.replace(",", ".")
        else:
            compact = compact.replace(",", "")
    elif "," in compact:
        compact = compact.replace(",", ".")

    try:
        return float(Decimal(compact))
    except (InvalidOperation, ValueError):
        return None


def normalize_datetime(value: Any) -> str | None:
    raw = as_text(value)
    if not raw:
        return None

    normalized = raw.replace("Z", "+00:00")
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        dt = None

    if dt is None:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")
