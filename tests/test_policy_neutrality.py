import json
import unittest
from pathlib import Path

from rikdom.funded_ratio import compute_funded_ratios
from rikdom.policy import validate_policy


class PolicyNeutralityTests(unittest.TestCase):
    def test_context_selected_account_type_is_not_limited_to_br_us_or_uk(self):
        policy = json.loads(Path("data-sample/policy.json").read_text())
        policy["accounts"] = [{"account_id": "local", "label": "Local pension", "tax_account_type": "sg_srs", "jurisdiction": "SG"}]
        policy.pop("tax_rules", None)
        self.assertEqual(validate_policy(policy), [])

    def test_projection_requires_currency_and_does_not_round_currency_units(self):
        with self.assertRaisesRegex(ValueError, "base_currency"):
            compute_funded_ratios(1.2345, {})
        self.assertEqual(compute_funded_ratios(1.2345, {}, base_currency="KWD").portfolio_value_base, 1.2345)
