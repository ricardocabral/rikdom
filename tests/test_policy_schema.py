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


class CapitalMarketAssumptionsTests(unittest.TestCase):
    def _with_cma(self, **kwargs) -> dict:
        policy = _load_sample()
        policy["capital_market_assumptions"] = {
            "as_of": "2026-01-01",
            "source": "manual",
            "currency_basis": "BRL",
            "horizon_years": 30,
            "buckets": [
                {
                    "dimension": "asset_class",
                    "bucket": "stocks",
                    "expected_real_return_pct": 5.0,
                    "volatility_pct": 18.0,
                },
                {
                    "dimension": "asset_class",
                    "bucket": "debt",
                    "expected_real_return_pct": 2.5,
                    "volatility_pct": 6.0,
                    "yield_pct": 5.5,
                },
            ],
            "correlations": [
                {
                    "a": {"dimension": "asset_class", "bucket": "stocks"},
                    "b": {"dimension": "asset_class", "bucket": "debt"},
                    "rho": 0.1,
                }
            ],
        }
        for key, value in kwargs.items():
            policy["capital_market_assumptions"][key] = value
        return policy

    def test_minimal_cma_is_accepted(self) -> None:
        policy = self._with_cma()
        self.assertEqual(validate_policy(policy), [])

    def test_duplicate_bucket_is_rejected(self) -> None:
        policy = self._with_cma()
        policy["capital_market_assumptions"]["buckets"].append(
            {
                "dimension": "asset_class",
                "bucket": "stocks",
                "expected_real_return_pct": 4.0,
            }
        )
        errors = validate_policy(policy)
        self.assertTrue(any("duplicate" in e.lower() for e in errors), errors)

    def test_correlation_referencing_unknown_bucket_is_rejected(self) -> None:
        policy = self._with_cma()
        policy["capital_market_assumptions"]["correlations"].append(
            {
                "a": {"dimension": "asset_class", "bucket": "stocks"},
                "b": {"dimension": "asset_class", "bucket": "missing"},
                "rho": 0.0,
            }
        )
        errors = validate_policy(policy)
        self.assertTrue(any("not declared in buckets" in e for e in errors), errors)

    def test_self_correlation_is_rejected(self) -> None:
        policy = self._with_cma()
        policy["capital_market_assumptions"]["correlations"].append(
            {
                "a": {"dimension": "asset_class", "bucket": "stocks"},
                "b": {"dimension": "asset_class", "bucket": "stocks"},
                "rho": 1.0,
            }
        )
        errors = validate_policy(policy)
        self.assertTrue(any("same bucket" in e for e in errors), errors)

    def test_rho_out_of_range_is_rejected(self) -> None:
        policy = self._with_cma()
        policy["capital_market_assumptions"]["correlations"][0]["rho"] = 2.0
        errors = validate_policy(policy)
        self.assertTrue(
            any("correlations" in e and ("rho" in e or "2.0" in e or "maximum" in e) for e in errors),
            errors,
        )


class SpendingPlanTests(unittest.TestCase):
    def _with_plan(self, **kwargs) -> dict:
        policy = _load_sample()
        policy["spending_plan"] = {
            "currency": "BRL",
            "basis": "today",
            "default_inflation_pct": 4.0,
            "essentials": {"annual_amount": {"amount": 96000, "currency": "BRL"}},
            "discretionary": {
                "annual_amount": {"amount": 60000, "currency": "BRL"},
                "inflation_pct": 4.0,
            },
            "healthcare": {
                "annual_amount": {"amount": 24000, "currency": "BRL"},
                "inflation_pct": 7.0,
                "coverage_gap_years": 5,
            },
            "lumpy_items": [
                {
                    "label": "Renovate kitchen",
                    "amount": {"amount": 80000, "currency": "BRL"},
                    "due_age": 62,
                    "category": "home",
                }
            ],
            "phases": [
                {"label": "go-go", "start_age": 60, "end_age": 74, "multiplier_pct": 110},
                {"label": "slow-go", "start_age": 75, "end_age": 84, "multiplier_pct": 95},
                {"label": "no-go", "start_age": 85, "end_age": 120, "multiplier_pct": 75},
            ],
        }
        for key, value in kwargs.items():
            policy["spending_plan"][key] = value
        return policy

    def test_minimal_spending_plan_is_accepted(self) -> None:
        policy = self._with_plan()
        self.assertEqual(validate_policy(policy), [])

    def test_overlapping_phases_is_rejected(self) -> None:
        policy = self._with_plan()
        policy["spending_plan"]["phases"][1]["start_age"] = 70
        errors = validate_policy(policy)
        self.assertTrue(any("overlaps" in e for e in errors), errors)

    def test_inverted_end_age_is_rejected(self) -> None:
        policy = self._with_plan()
        policy["spending_plan"]["phases"][0]["end_age"] = 50
        errors = validate_policy(policy)
        self.assertTrue(any("end_age" in e for e in errors), errors)

    def test_lumpy_item_requires_amount(self) -> None:
        policy = self._with_plan()
        del policy["spending_plan"]["lumpy_items"][0]["amount"]
        errors = validate_policy(policy)
        self.assertTrue(any("amount" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
