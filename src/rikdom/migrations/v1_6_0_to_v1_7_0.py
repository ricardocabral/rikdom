from __future__ import annotations

import copy
from typing import Any

from .base import Migration


def _upgrade(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(portfolio)
    new["schema_version"] = "1.7.0"
    return new, [
        "schema_version -> 1.7.0; optional statement and acquisition observations; no basis or history inferred"
    ]


migration = Migration(
    from_version=(1, 6, 0),
    to_version=(1, 7, 0),
    description="Preserve reported statement observations and valuation details.",
    upgrade=_upgrade,
)
