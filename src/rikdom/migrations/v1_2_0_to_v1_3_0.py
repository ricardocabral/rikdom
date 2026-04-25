from __future__ import annotations

import copy
from typing import Any

from .base import Migration


def _upgrade(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(portfolio)
    changes: list[str] = []

    new["schema_version"] = "1.3.0"
    changes.append("schema_version -> 1.3.0")
    changes.append("noted optional 'liabilities' slot availability")
    changes.append("noted optional 'tax_lots' slot availability")
    changes.append("noted optional 'holdings[].account_id' field availability")

    return new, changes


migration = Migration(
    from_version=(1, 2, 0),
    to_version=(1, 3, 0),
    description="Introduce optional liabilities ledger, tax_lots ledger, and holdings[].account_id soft reference.",
    upgrade=_upgrade,
)
