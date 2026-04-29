from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from rikdom.policy import validate_policy


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data-sample" / "policy.json"


def _load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


class BenchmarkResolutionTests(unittest.TestCase):
    def test_unknown_benchmark_id_on_target_is_error(self) -> None:
        policy = _load_sample()
        policy["strategic_allocation"]["targets"][0]["benchmark_id"] = "ghost-bench"
        errors = validate_policy(policy)
        self.assertTrue(
            any("ghost-bench" in e and "benchmark_id" in e for e in errors),
            errors,
        )

    def test_target_without_benchmark_id_is_ok(self) -> None:
        policy = _load_sample()
        policy["strategic_allocation"]["targets"][0].pop("benchmark_id", None)
        errors = validate_policy(policy)
        self.assertEqual(errors, [])

    def test_duplicate_benchmark_id_is_error(self) -> None:
        policy = _load_sample()
        policy["benchmarks"].append(copy.deepcopy(policy["benchmarks"][0]))
        errors = validate_policy(policy)
        self.assertTrue(any("duplicate id" in e for e in errors), errors)


class CompositeBenchmarkTests(unittest.TestCase):
    def test_composite_weights_must_sum_to_100(self) -> None:
        policy = _load_sample()
        for bench in policy["benchmarks"]:
            if bench["id"] == "global-stocks-blend":
                bench["components"][0]["weight_pct"] = 30
        errors = validate_policy(policy)
        self.assertTrue(
            any("must sum to ~100" in e for e in errors), errors
        )

    def test_composite_component_must_resolve(self) -> None:
        policy = _load_sample()
        for bench in policy["benchmarks"]:
            if bench["id"] == "global-stocks-blend":
                bench["components"][0]["benchmark_id"] = "ghost"
        errors = validate_policy(policy)
        self.assertTrue(
            any(
                "global-stocks-blend" not in e
                and "ghost" in e
                and "not declared" in e
                for e in errors
            ),
            errors,
        )

    def test_composite_cycle_detected(self) -> None:
        policy = _load_sample()
        policy["benchmarks"].append(
            {
                "id": "loop-a",
                "label": "loop A",
                "kind": "composite",
                "components": [{"benchmark_id": "loop-b", "weight_pct": 100}],
            }
        )
        policy["benchmarks"].append(
            {
                "id": "loop-b",
                "label": "loop B",
                "kind": "composite",
                "components": [{"benchmark_id": "loop-a", "weight_pct": 100}],
            }
        )
        errors = validate_policy(policy)
        self.assertTrue(
            any("composite cycle" in e for e in errors), errors
        )

    def test_components_only_allowed_on_composite(self) -> None:
        policy = _load_sample()
        for bench in policy["benchmarks"]:
            if bench["id"] == "ibov":
                bench["components"] = [
                    {"benchmark_id": "sp500", "weight_pct": 100}
                ]
        errors = validate_policy(policy)
        self.assertTrue(
            any("components only allowed for kind=composite" in e for e in errors),
            errors,
        )


class SamplePolicyTests(unittest.TestCase):
    def test_sample_validates_with_benchmarks(self) -> None:
        errors = validate_policy(_load_sample())
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
