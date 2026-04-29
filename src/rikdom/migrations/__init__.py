from __future__ import annotations

from typing import Any

from .base import (
    AppliedStep,
    Migration,
    Version,
    format_version,
    parse_version,
)
from .v1_0_0_to_v1_1_0 import migration as _m_1_0_0_to_1_1_0
from .v1_1_0_to_v1_2_0 import migration as _m_1_1_0_to_1_2_0
from .v1_2_0_to_v1_3_0 import migration as _m_1_2_0_to_1_3_0
from .v1_3_0_to_v1_4_0 import migration as _m_1_3_0_to_1_4_0


MIGRATIONS: list[Migration] = [
    _m_1_0_0_to_1_1_0,
    _m_1_1_0_to_1_2_0,
    _m_1_2_0_to_1_3_0,
    _m_1_3_0_to_1_4_0,
]


class MigrationPlanError(Exception):
    pass


def plan_migrations(current: Version, target: Version) -> list[Migration]:
    if current == target:
        return []
    if current > target:
        raise MigrationPlanError(
            f"downgrade not supported: {format_version(current)} -> {format_version(target)}"
        )

    by_from: dict[Version, Migration] = {m.from_version: m for m in MIGRATIONS}
    steps: list[Migration] = []
    cursor = current
    while cursor != target:
        step = by_from.get(cursor)
        if step is None:
            raise MigrationPlanError(
                f"no migration path from {format_version(cursor)} toward {format_version(target)}"
            )
        steps.append(step)
        cursor = step.to_version
        if cursor > target:
            raise MigrationPlanError(
                f"migration overshoots target: reached {format_version(cursor)} past {format_version(target)}"
            )
    return steps


def apply_migrations(
    portfolio: dict[str, Any], steps: list[Migration]
) -> tuple[dict[str, Any], list[AppliedStep]]:
    current = portfolio
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
    "AppliedStep",
    "MIGRATIONS",
    "Migration",
    "MigrationPlanError",
    "Version",
    "apply_migrations",
    "format_version",
    "parse_version",
    "plan_migrations",
]
