"""Neutral parsing primitives with conventions chosen explicitly by callers."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone, tzinfo
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


def parse_decimal(
    value: Any, *, decimal_separator: str, grouping_separator: str | None = None
) -> float | None:
    """Parse a finite number using the source's declared separators.

    Currency symbols and other provider decorations belong to the caller.
    Invalid grouping is rejected rather than reinterpreted as another locale.
    """
    if decimal_separator not in (".", ","):
        raise ValueError("decimal_separator must be '.' or ','")
    if grouping_separator == decimal_separator:
        raise ValueError("grouping and decimal separators must differ")
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) else None
    raw = as_text(value)
    integer = r"[0-9]+"
    if grouping_separator:
        group = re.escape(grouping_separator)
        integer = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{group}[0-9]{{3}})+)"
    decimal = re.escape(decimal_separator)
    if not re.fullmatch(rf"[+-]?(?:{integer}(?:{decimal}[0-9]*)?|{decimal}[0-9]+)(?:[eE][+-]?[0-9]+)?", raw):
        return None
    if grouping_separator:
        raw = raw.replace(grouping_separator, "")
    raw = raw.replace(decimal_separator, ".")
    try:
        number = float(Decimal(raw))
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def normalize_datetime(
    value: Any, *, naive_timezone: tzinfo | None, date_formats: tuple[str, ...] = ()
) -> str | None:
    """Read ISO dates or declared source formats, with an explicit naive zone.

    Pass None to reject timestamps that omit a timezone.
    """
    raw = as_text(value)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None:
        for fmt in date_formats:
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        if naive_timezone is None:
            return None
        dt = dt.replace(tzinfo=naive_timezone)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def with_import_diagnostics(
    payload: dict[str, Any], *, history_coverage: list[dict[str, Any]],
    unsupported_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach source-declared diagnostics without interpreting their meaning."""
    metadata = payload.setdefault("metadata", {})
    metadata["rikdom_import_diagnostics"] = {
        "version": 1,
        "history_coverage": history_coverage,
        "unsupported_events": unsupported_events,
    }
    return payload
