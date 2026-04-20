from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


Version = tuple[int, int, int]

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(value: str) -> Version:
    match = _SEMVER_RE.match(value)
    if not match:
        raise ValueError(f"invalid semver '{value}'; expected MAJOR.MINOR.PATCH")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def format_version(value: Version) -> str:
    return ".".join(str(p) for p in value)


@dataclass(frozen=True)
class Migration:
    from_version: Version
    to_version: Version
    description: str
    upgrade: Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]]


@dataclass(frozen=True)
class PlannedStep:
    migration: Migration


@dataclass(frozen=True)
class AppliedStep:
    from_version: Version
    to_version: Version
    description: str
    changes: list[str]
