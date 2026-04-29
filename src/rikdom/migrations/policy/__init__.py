from __future__ import annotations

from typing import Any

from ..base import (
    AppliedStep,
    Migration,
    Version,
    format_version,
    parse_version,
)
from .v0_1_0_to_v0_2_0 import migration as _m_0_1_0_to_0_2_0
from .v0_2_0_to_v0_3_0 import migration as _m_0_2_0_to_0_3_0


POLICY_MIGRATIONS: list[Migration] = [
    _m_0_1_0_to_0_2_0,
    _m_0_2_0_to_0_3_0,
]


class PolicyMigrationPlanError(Exception):
    pass


def plan_policy_migrations(current: Version, target: Version) -> list[Migration]:
    if current == target:
        return []
    if current > target:
        raise PolicyMigrationPlanError(
            f"downgrade not supported: {format_version(current)} -> {format_version(target)}"
        )

    by_from: dict[Version, Migration] = {m.from_version: m for m in POLICY_MIGRATIONS}
    steps: list[Migration] = []
    cursor = current
    while cursor != target:
        step = by_from.get(cursor)
        if step is None:
            raise PolicyMigrationPlanError(
                f"no policy migration path from {format_version(cursor)} toward {format_version(target)}"
            )
        steps.append(step)
        cursor = step.to_version
        if cursor > target:
            raise PolicyMigrationPlanError(
                f"policy migration overshoots target: reached {format_version(cursor)} past {format_version(target)}"
            )
    return steps


def apply_policy_migrations(
    policy: dict[str, Any], steps: list[Migration]
) -> tuple[dict[str, Any], list[AppliedStep]]:
    current = policy
    applied: list[AppliedStep] = []
    for migration in steps:
        current, changes = migration.upgrade(current)
        applied.append(
            AppliedStep(
                from_version=migration.from_version,
                to_version=migration.to_version,
                description=migration.description,
                changes=changes,
            )
        )
    return current, applied


__all__ = [
    "POLICY_MIGRATIONS",
    "PolicyMigrationPlanError",
    "apply_policy_migrations",
    "format_version",
    "parse_version",
    "plan_policy_migrations",
]
