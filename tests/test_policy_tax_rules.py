from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from rikdom.migrations.policy import (
    apply_policy_migrations,
    plan_policy_migrations,
)
from rikdom.policy import CURRENT_POLICY_SCHEMA_VERSION, validate_policy


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data-sample" / "policy.json"


def _load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


class TaxRulesShapeTests(unittest.TestCase):
    def test_sample_validates(self) -> None:
        errors = validate_policy(_load_sample())
        self.assertEqual(errors, [])

    def test_duplicate_rule_id_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_rules"].append(copy.deepcopy(policy["tax_rules"][0]))
        errors = validate_policy(policy)
        self.assertTrue(
            any("tax_rules" in e and "duplicate id" in e for e in errors), errors
        )

    def test_unknown_tax_account_type_warns(self) -> None:
        policy = _load_sample()
        policy["tax_rules"][0]["applies_to"]["tax_account_types"] = [
            "bogus_account_type"
        ]
        errors = validate_policy(policy)
        self.assertTrue(
            any(
                "bogus_account_type" in e and "rule will never match" in e
                for e in errors
            ),
            errors,
        )

    def test_holding_period_window_inverted_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_rules"][0]["applies_to"]["holding_period_days_min"] = 100
        policy["tax_rules"][0]["applies_to"]["holding_period_days_max"] = 50
        errors = validate_policy(policy)
        self.assertTrue(
            any(
                "holding_period_days_min" in e and "must be <=" in e
                for e in errors
            ),
            errors,
        )

    def test_effective_dates_inverted_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_rules"][0]["effective_from"] = "2030-01-01"
        policy["tax_rules"][0]["effective_to"] = "2020-01-01"
        errors = validate_policy(policy)
        self.assertTrue(
            any("effective_from" in e and "must be" in e for e in errors), errors
        )

    def test_rate_pct_out_of_range_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_rules"][0]["rate_pct"] = 150
        errors = validate_policy(policy)
        self.assertTrue(any("rate_pct" in e for e in errors), errors)

    def test_invalid_event_kind_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_rules"][0]["applies_to"]["event_kinds"] = ["telekinesis"]
        errors = validate_policy(policy)
        self.assertTrue(any("event_kinds" in e for e in errors), errors)

    def test_brackets_pass_through(self) -> None:
        policy = _load_sample()
        # the regressive rule already has brackets; just confirm it validates
        errors = validate_policy(policy)
        self.assertEqual(errors, [])


class TaxExemptionsTests(unittest.TestCase):
    def test_sample_exemption_validates(self) -> None:
        errors = validate_policy(_load_sample())
        self.assertEqual(errors, [])

    def test_duplicate_exemption_id_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_exemptions"].append(
            copy.deepcopy(policy["tax_exemptions"][0])
        )
        errors = validate_policy(policy)
        self.assertTrue(
            any("tax_exemptions" in e and "duplicate id" in e for e in errors),
            errors,
        )

    def test_exemption_effective_dates_inverted_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_exemptions"][0]["effective_from"] = "2030-01-01"
        policy["tax_exemptions"][0]["effective_to"] = "2020-01-01"
        errors = validate_policy(policy)
        self.assertTrue(
            any("tax_exemptions" in e and "effective_from" in e for e in errors),
            errors,
        )

    def test_unknown_threshold_period_rejected(self) -> None:
        policy = _load_sample()
        policy["tax_exemptions"][0]["threshold_period"] = "fortnight"
        errors = validate_policy(policy)
        self.assertTrue(any("threshold_period" in e for e in errors), errors)


class PolicyMigration020to030Tests(unittest.TestCase):
    def test_legacy_020_upgrades_and_validates(self) -> None:
        policy = _load_sample()
        policy["schema_version"] = "0.2.0"
        policy.pop("tax_rules", None)
        policy.pop("tax_exemptions", None)

        steps = plan_policy_migrations((0, 2, 0), CURRENT_POLICY_SCHEMA_VERSION)
        result, applied = apply_policy_migrations(policy, steps)
        self.assertEqual(result["schema_version"], "0.3.0")
        self.assertEqual(validate_policy(result), [])
        self.assertEqual(len(applied), 1)
        self.assertTrue(any("tax_rules" in c for c in applied[0].changes))

    def test_full_chain_010_to_current(self) -> None:
        policy = _load_sample()
        policy["schema_version"] = "0.1.0"
        policy.pop("benchmarks", None)
        policy.pop("tax_rules", None)
        policy.pop("tax_exemptions", None)
        for t in policy["strategic_allocation"]["targets"]:
            t.pop("benchmark_id", None)

        steps = plan_policy_migrations((0, 1, 0), CURRENT_POLICY_SCHEMA_VERSION)
        result, applied = apply_policy_migrations(policy, steps)
        self.assertEqual(result["schema_version"], "0.3.0")
        self.assertEqual(len(applied), 2)
        self.assertEqual(validate_policy(result), [])


if __name__ == "__main__":
    unittest.main()
