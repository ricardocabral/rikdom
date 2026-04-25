"""Validation for the Investment Policy Statement (IPS) schema.

Runs the JSON Schema structural check plus semantic checks that JSON Schema
2020-12 cannot express (cross-field band invariants on AllocationTarget).
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    resource = files("rikdom._resources").joinpath("policy.schema.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_policy(policy: Any) -> list[str]:
    """Return a list of human-readable validation errors; empty means valid."""
    errors: list[str] = []
    validator = _schema_validator()
    for err in sorted(validator.iter_errors(policy), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    errors.extend(_semantic_checks(policy))
    return errors


def _semantic_checks(policy: Any) -> list[str]:
    if not isinstance(policy, dict):
        return []
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

    cma = policy.get("capital_market_assumptions")
    if isinstance(cma, dict):
        errors.extend(_check_capital_market_assumptions(cma))

    plan = policy.get("spending_plan")
    if isinstance(plan, dict):
        errors.extend(_check_spending_plan(plan))
    return errors


def _check_capital_market_assumptions(cma: dict) -> list[str]:
    errors: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    buckets = cma.get("buckets") or []
    if isinstance(buckets, list):
        for idx, bucket in enumerate(buckets):
            if not isinstance(bucket, dict):
                continue
            dim = str(bucket.get("dimension", ""))
            buc = str(bucket.get("bucket", ""))
            key = (dim, buc)
            if key in seen_pairs:
                errors.append(
                    f"capital_market_assumptions.buckets[{idx}]: duplicate "
                    f"(dimension={dim}, bucket={buc})"
                )
            else:
                seen_pairs.add(key)

    correlations = cma.get("correlations") or []
    if isinstance(correlations, list):
        for idx, corr in enumerate(correlations):
            if not isinstance(corr, dict):
                continue
            a = corr.get("a") or {}
            b = corr.get("b") or {}
            for side, label in ((a, "a"), (b, "b")):
                if not isinstance(side, dict):
                    continue
                key = (str(side.get("dimension", "")), str(side.get("bucket", "")))
                if seen_pairs and key not in seen_pairs:
                    errors.append(
                        f"capital_market_assumptions.correlations[{idx}].{label} "
                        f"(dimension={key[0]}, bucket={key[1]}) not declared in buckets"
                    )
            if a == b:
                errors.append(
                    f"capital_market_assumptions.correlations[{idx}]: a and b refer to the same bucket"
                )
    return errors


def _check_spending_plan(plan: dict) -> list[str]:
    errors: list[str] = []
    phases = plan.get("phases") or []
    if not isinstance(phases, list):
        return errors

    intervals: list[tuple[int, int, int]] = []  # (start, end, idx)
    for idx, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        start = phase.get("start_age")
        end = phase.get("end_age")
        if not isinstance(start, int):
            continue
        end_val = end if isinstance(end, int) else 999
        if isinstance(end, int) and end < start:
            errors.append(
                f"spending_plan.phases[{idx}]: end_age ({end}) must be >= start_age ({start})"
            )
        intervals.append((start, end_val, idx))

    intervals.sort()
    for i in range(1, len(intervals)):
        prev_start, prev_end, prev_idx = intervals[i - 1]
        cur_start, cur_end, cur_idx = intervals[i]
        if cur_start <= prev_end:
            errors.append(
                f"spending_plan.phases[{prev_idx}] (start_age {prev_start}) overlaps "
                f"with phases[{cur_idx}] (start_age {cur_start})"
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
