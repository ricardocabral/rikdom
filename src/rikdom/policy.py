"""Validation for the Investment Policy Statement (IPS) schema.

Runs the JSON Schema structural check plus semantic checks that JSON Schema
2020-12 cannot express (cross-field band invariants on AllocationTarget).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "policy.schema.json"


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_policy(policy: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation errors; empty means valid."""
    errors: list[str] = []
    validator = _schema_validator()
    for err in sorted(validator.iter_errors(policy), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    errors.extend(_semantic_checks(policy))
    return errors


def _semantic_checks(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    strat = policy.get("strategic_allocation")
    if isinstance(strat, dict):
        for idx, target in enumerate(strat.get("targets", []) or []):
            errors.extend(
                _check_allocation_target(
                    f"strategic_allocation.targets[{idx}]", target
                )
            )

    glide = policy.get("glide_path")
    if isinstance(glide, dict):
        for n_idx, node in enumerate(glide.get("nodes", []) or []):
            if not isinstance(node, dict):
                continue
            for o_idx, target in enumerate(node.get("overrides", []) or []):
                errors.extend(
                    _check_allocation_target(
                        f"glide_path.nodes[{n_idx}].overrides[{o_idx}]", target
                    )
                )
    return errors


def _check_allocation_target(path: str, target: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(target, dict):
        return errors
    weight = target.get("weight_pct")
    lo = target.get("min_pct")
    hi = target.get("max_pct")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
        errors.append(f"{path}: min_pct ({lo}) must be <= max_pct ({hi})")
    if isinstance(weight, (int, float)):
        if isinstance(lo, (int, float)) and weight < lo:
            errors.append(
                f"{path}: weight_pct ({weight}) must be >= min_pct ({lo})"
            )
        if isinstance(hi, (int, float)) and weight > hi:
            errors.append(
                f"{path}: weight_pct ({weight}) must be <= max_pct ({hi})"
            )
    return errors
