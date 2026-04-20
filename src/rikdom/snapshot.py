from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .aggregate import AggregateResult



def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def snapshot_from_aggregate(result: AggregateResult, timestamp: str | None = None) -> dict[str, Any]:
    return {
        "timestamp": timestamp or utc_now_iso(),
        "base_currency": result.base_currency,
        "totals": {
            "portfolio_value_base": result.total_value_base,
            "by_asset_class": result.by_asset_class,
        },
    }
