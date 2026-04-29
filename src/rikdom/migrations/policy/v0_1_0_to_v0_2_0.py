from __future__ import annotations

import copy
from typing import Any

from ..base import Migration


def _upgrade(policy: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    new = copy.deepcopy(policy)
    changes: list[str] = []

    new["schema_version"] = "0.2.0"
    changes.append("schema_version -> 0.2.0")
    changes.append(
        "noted optional 'benchmarks' top-level slot for benchmark registry"
    )
    changes.append(
        "noted optional 'benchmark_id' on strategic_allocation.targets[] entries"
    )

    return new, changes


migration = Migration(
    from_version=(0, 1, 0),
    to_version=(0, 2, 0),
    description=(
        "Introduce benchmarks registry and per-target benchmark_id soft reference."
    ),
    upgrade=_upgrade,
)
