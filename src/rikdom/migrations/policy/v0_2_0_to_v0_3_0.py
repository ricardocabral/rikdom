from __future__ import annotations

import copy
from typing import Any

from ..base import Migration


def _upgrade(policy: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(policy)
    changes: list[str] = []

    new["schema_version"] = "0.3.0"
    changes.append("schema_version -> 0.3.0")
    changes.append(
        "noted optional 'tax_rules' top-level slot for jurisdiction-aware tax-rate table"
    )
    changes.append(
        "noted optional 'tax_exemptions' top-level slot for structured thresholds (e.g., BR isenção)"
    )

    return new, changes


migration = Migration(
    from_version=(0, 2, 0),
    to_version=(0, 3, 0),
    description=(
        "Introduce tax_rules and tax_exemptions slots so agents can ground "
        "tax-aware advice in declared rates rather than guessing."
    ),
    upgrade=_upgrade,
)
