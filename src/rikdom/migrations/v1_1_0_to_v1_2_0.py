from __future__ import annotations

import copy
from typing import Any

from .base import Migration


def _upgrade(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(portfolio)
    changes: list[str] = []

    new["schema_version"] = "1.2.0"
    changes.append("schema_version -> 1.2.0")

    if "operations" not in new:
        # Left absent by default; the slot is optional in the schema.
        changes.append("noted optional 'operations' slot availability")

    return new, changes


migration = Migration(
    from_version=(1, 1, 0),
    to_version=(1, 2, 0),
    description="Introduce optional operational task catalog/events slot.",
    upgrade=_upgrade,
)
