from __future__ import annotations

import copy
from typing import Any

from .base import Migration


def _upgrade(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(portfolio)
    new["schema_version"] = "1.6.0"
    return new, [
        "schema_version -> 1.6.0",
        "noted optional dated activities, amortization, corporate_action legs, signed cost_basis_adjustment and rikdom_instrument_history; no history or basis inferred",
    ]


migration = Migration(
    from_version=(1, 5, 0),
    to_version=(1, 6, 0),
    description="Add optional instrument history, settlement dates and corporate actions.",
    upgrade=_upgrade,
)
