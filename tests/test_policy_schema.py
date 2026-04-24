from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from rikdom.policy import validate_policy


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data-sample" / "policy.json"


def _load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


class PolicySampleTests(unittest.TestCase):
    def test_data_sample_policy_validates(self) -> None:
        errors = validate_policy(_load_sample())
        self.assertEqual(errors, [], msg=f"Expected valid sample policy, got: {errors}")


class GlidePathNodeTests(unittest.TestCase):
    def test_node_without_anchor_is_rejected(self) -> None:
        policy = _load_sample()
        policy["glide_path"]["nodes"][0].pop("age")
        errors = validate_policy(policy)
        self.assertTrue(
            any("glide_path" in e and "nodes" in e for e in errors),
            msg=f"Expected glide_path node anchor error, got: {errors}",
        )

    def test_node_with_both_anchors_is_rejected(self) -> None:
        policy = _load_sample()
        policy["glide_path"]["nodes"][0]["as_of_date"] = "2030-01-01"
        errors = validate_policy(policy)
        self.assertTrue(
            any("glide_path" in e and "nodes" in e for e in errors),
            msg=f"Expected exclusive-anchor error, got: {errors}",
        )

    def test_age_based_mode_rejects_date_anchored_node(self) -> None:
        policy = _load_sample()
        policy["glide_path"]["mode"] = "age_based"
        policy["glide_path"]["nodes"][0] = {
            "as_of_date": "2040-01-01",
            "overrides": [
                {"dimension": "asset_class", "bucket": "stocks", "weight_pct": 60}
            ],
        }
        errors = validate_policy(policy)
        self.assertTrue(
            any("glide_path" in e for e in errors),
            msg=f"Expected mode/anchor mismatch error, got: {errors}",
        )

    def test_date_based_mode_rejects_age_anchored_node(self) -> None:
        policy = _load_sample()
        policy["glide_path"]["mode"] = "date_based"
        policy["glide_path"]["nodes"] = [
            {
                "age": 50,
                "overrides": [
                    {"dimension": "asset_class", "bucket": "stocks", "weight_pct": 60}
                ],
            }
        ]
        errors = validate_policy(policy)
        self.assertTrue(
            any("glide_path" in e for e in errors),
            msg=f"Expected date_based/age mismatch error, got: {errors}",
        )

    def test_static_mode_rejects_any_nodes(self) -> None:
        policy = _load_sample()
        policy["glide_path"]["mode"] = "static"
        errors = validate_policy(policy)
        self.assertTrue(
            any("glide_path" in e and "nodes" in e for e in errors),
            msg=f"Expected static-mode nodes error, got: {errors}",
        )

    def test_date_based_mode_with_date_nodes_validates(self) -> None:
        policy = _load_sample()
        policy["glide_path"]["mode"] = "date_based"
        policy["glide_path"]["nodes"] = [
            {
                "as_of_date": "2035-06-15",
                "overrides": [
                    {"dimension": "asset_class", "bucket": "stocks", "weight_pct": 60}
                ],
            }
        ]
        errors = validate_policy(policy)
        self.assertEqual(errors, [], msg=f"Expected valid date-based glide path, got: {errors}")


class AllocationBandTests(unittest.TestCase):
    def test_min_greater_than_max_is_rejected(self) -> None:
        policy = _load_sample()
        target = policy["strategic_allocation"]["targets"][0]
        target["min_pct"] = 80
        target["max_pct"] = 70
        target["weight_pct"] = 75
        errors = validate_policy(policy)
        self.assertTrue(
            any("min_pct" in e and "max_pct" in e for e in errors),
            msg=f"Expected min>max band error, got: {errors}",
        )

    def test_weight_below_min_is_rejected(self) -> None:
        policy = _load_sample()
        target = policy["strategic_allocation"]["targets"][0]
        target["min_pct"] = 80
        target["max_pct"] = 90
        target["weight_pct"] = 50
        errors = validate_policy(policy)
        self.assertTrue(
            any("weight_pct" in e and "min_pct" in e for e in errors),
            msg=f"Expected weight<min error, got: {errors}",
        )

    def test_weight_above_max_is_rejected(self) -> None:
        policy = _load_sample()
        target = policy["strategic_allocation"]["targets"][0]
        target["min_pct"] = 10
        target["max_pct"] = 20
        target["weight_pct"] = 50
        errors = validate_policy(policy)
        self.assertTrue(
            any("weight_pct" in e and "max_pct" in e for e in errors),
            msg=f"Expected weight>max error, got: {errors}",
        )

    def test_band_violation_in_glide_path_override_is_reported(self) -> None:
        policy = _load_sample()
        override = policy["glide_path"]["nodes"][0]["overrides"][0]
        override["min_pct"] = 90
        override["max_pct"] = 95
        override["weight_pct"] = 50
        errors = validate_policy(policy)
        self.assertTrue(
            any("glide_path" in e and "weight_pct" in e for e in errors),
            msg=f"Expected glide-path override band error, got: {errors}",
        )


class PolicyRegressionTests(unittest.TestCase):
    def test_unchanged_sample_round_trips(self) -> None:
        policy = _load_sample()
        errors = validate_policy(copy.deepcopy(policy))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
