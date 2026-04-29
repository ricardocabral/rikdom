"""Validation for the Investment Policy Statement (IPS) schema.

Runs the JSON Schema structural check plus semantic checks that JSON Schema
2020-12 cannot express (cross-field band invariants on AllocationTarget,
benchmark resolution, composite-benchmark cycle/weight checks).
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator


CANONICAL_POLICY_SCHEMA_URI = "https://example.org/rikdom/schema/policy.schema.json"
CURRENT_POLICY_SCHEMA_VERSION = (0, 3, 0)
MIN_COMPATIBLE_POLICY_SCHEMA_VERSION = (0, 1, 0)

BENCHMARK_COMPOSITE_SUM_MIN = 99.5
BENCHMARK_COMPOSITE_SUM_MAX = 100.5


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

    errors.extend(_check_benchmarks(policy))
    errors.extend(_check_tax_rules(policy))
    return errors


def _check_tax_rules(policy: dict) -> list[str]:
    errors: list[str] = []
    rules = policy.get("tax_rules")
    declared_account_types: set[str] = set()
    accounts = policy.get("accounts")
    if isinstance(accounts, list):
        for account in accounts:
            if isinstance(account, dict):
                tat = account.get("tax_account_type")
                if isinstance(tat, str) and tat:
                    declared_account_types.add(tat)

    if rules is not None:
        if not isinstance(rules, list):
            errors.append("tax_rules must be an array when provided")
            return errors
        seen_ids: set[str] = set()
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            rid = rule.get("id")
            if isinstance(rid, str) and rid:
                if rid in seen_ids:
                    errors.append(f"tax_rules[{idx}]: duplicate id '{rid}'")
                else:
                    seen_ids.add(rid)

            applies = rule.get("applies_to")
            if isinstance(applies, dict):
                referenced = applies.get("tax_account_types")
                if isinstance(referenced, list) and declared_account_types:
                    for r_idx, ref in enumerate(referenced):
                        if (
                            isinstance(ref, str)
                            and ref
                            and ref not in declared_account_types
                        ):
                            errors.append(
                                f"tax_rules[{idx}].applies_to.tax_account_types[{r_idx}] "
                                f"'{ref}' not used by any account; "
                                "rule will never match"
                            )
                hp_min = applies.get("holding_period_days_min")
                hp_max = applies.get("holding_period_days_max")
                if (
                    isinstance(hp_min, int)
                    and isinstance(hp_max, int)
                    and hp_min > hp_max
                ):
                    errors.append(
                        f"tax_rules[{idx}].applies_to.holding_period_days_min "
                        f"({hp_min}) must be <= holding_period_days_max ({hp_max})"
                    )

            from_date = rule.get("effective_from")
            to_date = rule.get("effective_to")
            if (
                isinstance(from_date, str)
                and isinstance(to_date, str)
                and from_date > to_date
            ):
                errors.append(
                    f"tax_rules[{idx}]: effective_from ({from_date}) must be "
                    f"<= effective_to ({to_date})"
                )

    exemptions = policy.get("tax_exemptions")
    if exemptions is not None:
        if not isinstance(exemptions, list):
            errors.append("tax_exemptions must be an array when provided")
            return errors
        seen_ids = set()
        for idx, ex in enumerate(exemptions):
            if not isinstance(ex, dict):
                continue
            eid = ex.get("id")
            if isinstance(eid, str) and eid:
                if eid in seen_ids:
                    errors.append(f"tax_exemptions[{idx}]: duplicate id '{eid}'")
                else:
                    seen_ids.add(eid)
            from_date = ex.get("effective_from")
            to_date = ex.get("effective_to")
            if (
                isinstance(from_date, str)
                and isinstance(to_date, str)
                and from_date > to_date
            ):
                errors.append(
                    f"tax_exemptions[{idx}]: effective_from ({from_date}) must be "
                    f"<= effective_to ({to_date})"
                )
    return errors


def _check_benchmarks(policy: dict) -> list[str]:
    errors: list[str] = []
    benchmarks = policy.get("benchmarks")
    declared: dict[str, dict] = {}
    if benchmarks is not None:
        if not isinstance(benchmarks, list):
            errors.append("benchmarks must be an array when provided")
            return errors
        seen: set[str] = set()
        for idx, bench in enumerate(benchmarks):
            if not isinstance(bench, dict):
                continue
            bid = bench.get("id")
            if not isinstance(bid, str) or not bid:
                continue
            if bid in seen:
                errors.append(f"benchmarks[{idx}]: duplicate id '{bid}'")
            else:
                seen.add(bid)
                declared[bid] = bench

        for idx, bench in enumerate(benchmarks):
            if not isinstance(bench, dict):
                continue
            kind = bench.get("kind")
            components = bench.get("components")
            if components is not None and not isinstance(components, list):
                errors.append(f"benchmarks[{idx}].components must be an array")
                continue
            if kind == "composite":
                if not components:
                    errors.append(
                        f"benchmarks[{idx}]: kind=composite requires at least one component"
                    )
                    continue
                total = 0.0
                for c_idx, comp in enumerate(components):
                    if not isinstance(comp, dict):
                        continue
                    ref = comp.get("benchmark_id")
                    weight = comp.get("weight_pct")
                    if not isinstance(ref, str) or not ref:
                        continue
                    if declared and ref not in declared:
                        errors.append(
                            f"benchmarks[{idx}].components[{c_idx}].benchmark_id "
                            f"'{ref}' not declared in benchmarks[]"
                        )
                    if isinstance(weight, (int, float)) and not isinstance(
                        weight, bool
                    ):
                        total += float(weight)
                if not (
                    BENCHMARK_COMPOSITE_SUM_MIN
                    <= total
                    <= BENCHMARK_COMPOSITE_SUM_MAX
                ):
                    errors.append(
                        f"benchmarks[{idx}].components weight_pct must sum to ~100 "
                        f"(got {total})"
                    )
            elif components:
                errors.append(
                    f"benchmarks[{idx}]: components only allowed for kind=composite"
                )

        # Composite cycle detection (DFS).
        def _has_cycle(start: str) -> bool:
            stack: list[tuple[str, list[str]]] = [(start, [start])]
            while stack:
                node, path = stack.pop()
                bench = declared.get(node)
                if not isinstance(bench, dict) or bench.get("kind") != "composite":
                    continue
                for comp in bench.get("components") or []:
                    if not isinstance(comp, dict):
                        continue
                    nxt = comp.get("benchmark_id")
                    if not isinstance(nxt, str):
                        continue
                    if nxt in path:
                        return True
                    if nxt in declared:
                        stack.append((nxt, path + [nxt]))
            return False

        cycles_reported: set[str] = set()
        for bid in declared:
            if bid in cycles_reported:
                continue
            if _has_cycle(bid):
                errors.append(
                    f"benchmarks: composite cycle detected starting at '{bid}'"
                )
                cycles_reported.add(bid)

    # Cross-reference benchmark_id from strategic_allocation targets.
    strat = policy.get("strategic_allocation")
    if isinstance(strat, dict):
        for idx, target in enumerate(strat.get("targets", []) or []):
            if not isinstance(target, dict):
                continue
            ref = target.get("benchmark_id")
            if isinstance(ref, str) and ref and declared and ref not in declared:
                errors.append(
                    f"strategic_allocation.targets[{idx}].benchmark_id "
                    f"'{ref}' not declared in benchmarks[]"
                )
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
