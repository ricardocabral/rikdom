from __future__ import annotations

import copy
from typing import Any

from .base import Migration


def _upgrade(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(portfolio)
    changes: list[str] = []

    new["schema_version"] = "1.4.0"
    changes.append("schema_version -> 1.4.0")
    changes.append(
        "noted expanded activity event_type vocabulary "
        "(merger, contribution, withdrawal, tax_withheld, fx_conversion)"
    )
    changes.append(
        "noted optional activity slots: account_id, holding_id, tax_lot_ids, "
        "withholding_tax, realized_gain, fx_rate, counter_money"
    )

    return new, changes


migration = Migration(
    from_version=(1, 3, 0),
    to_version=(1, 4, 0),
    description=(
        "Expand activity event taxonomy and add optional cost-basis / "
        "income / tax / FX-conversion fields."
    ),
    upgrade=_upgrade,
)
