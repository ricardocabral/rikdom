from __future__ import annotations

import copy
from typing import Any

from .base import Migration


def _upgrade(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(portfolio)
    changes: list[str] = []

    new["schema_version"] = "1.5.0"
    changes.append("schema_version -> 1.5.0")
    changes.append(
        "noted optional Money.fx_ref slot for line-item FX provenance "
        "(as_of_date, base_currency, quote_currency, rate_to_base, source)"
    )

    return new, changes


migration = Migration(
    from_version=(1, 4, 0),
    to_version=(1, 5, 0),
    description=(
        "Add optional fx_ref to Money so each foreign-currency value can be "
        "sourced to a row in fx_rates.jsonl."
    ),
    upgrade=_upgrade,
)
