from __future__ import annotations

import copy
from typing import Any

from .base import Migration

CANONICAL_SCHEMA_URI = "https://example.org/rikdom/schema/portfolio.schema.json"


def _upgrade(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(portfolio)
    changes: list[str] = []

    new["schema_version"] = "1.1.0"
    changes.append("schema_version -> 1.1.0")

    if new.get("schema_uri") != CANONICAL_SCHEMA_URI:
        new["schema_uri"] = CANONICAL_SCHEMA_URI
        changes.append(f"schema_uri -> {CANONICAL_SCHEMA_URI}")

    if "activities" not in new:
        new["activities"] = []
        changes.append("added optional 'activities' slot (empty)")

    return new, changes


migration = Migration(
    from_version=(1, 0, 0),
    to_version=(1, 1, 0),
    description="Introduce optional activities ledger slot; normalize schema_uri.",
    upgrade=_upgrade,
)
