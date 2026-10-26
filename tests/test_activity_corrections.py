import copy
import unittest

from rikdom.activities import effective_activities, validate_activity_import, check_financial_contract
from rikdom.plugins import merge_activities


def activity(name, quantity=1, target=None, key=None):
    a = {"id": name, "idempotency_key": key or name, "event_type": "buy", "status": "posted", "effective_at": "2026-01-01T00:00:00Z", "quantity": quantity}
    if target:
        a["extensions"] = {"rikdom_correction": {"version": 1, "supersedes_activity_id": target, "reason": "Correct source quantity"}}
    return a


class CorrectionTests(unittest.TestCase):
    def test_chain_counts_only_latest_and_projection_is_composable(self):
        ledger = [activity("a"), activity("b", 2, "a"), activity("c", 3, "b")]
        original = copy.deepcopy(ledger)
        selected = effective_activities(ledger)
        self.assertEqual([a["quantity"] for a in selected], [3])
        self.assertEqual(effective_activities(selected), selected)
        self.assertEqual(ledger, original)

    def test_collision_cannot_overwrite_original_even_with_new_id(self):
        p = {"schema_version": "1.7.0", "activities": [activity("a")]}
        before = copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError, "idempotency"):
            merge_activities(p, {"activities": [activity("b", 2, "a", key="a")]})
        self.assertEqual(p, before)

    def test_old_correction_replay_remains_noop_after_another_correction(self):
        ledger = [activity("a"), activity("b", 2, "a"), activity("c", 3, "b")]
        p = {"schema_version": "2.0.0", "activities": ledger}
        validate_activity_import(p, {"activities": [activity("b", 2, "a")]})
        _, counts = merge_activities(p, {"activities": [activity("b", 2, "a")]})
        self.assertEqual(counts.skipped, 1)
        self.assertEqual(len(p["activities"]), 3)

    def test_forks_missing_targets_cycles_and_unknown_versions_are_rejected(self):
        cases = [
            [activity("a"), activity("b", 2, "a"), activity("c", 3, "a")],
            [activity("b", 2, "missing")],
            [activity("a", 1, "b"), activity("b", 2, "a")],
        ]
        for ledger in cases:
            with self.subTest(ledger=ledger), self.assertRaises(ValueError):
                effective_activities(ledger)
        bad = activity("b", 2, "a")
        bad["extensions"]["rikdom_correction"]["version"] = 99
        with self.assertRaises(ValueError):
            effective_activities([activity("a"), bad])

    def test_corrected_data_cannot_masquerade_as_legacy(self):
        with self.assertRaisesRegex(ValueError, "2.0.0"):
            check_financial_contract({"schema_version": "1.7.0", "activities": [activity("a"), activity("b", 2, "a")]})
        check_financial_contract({"schema_version": "2.0.0", "activities": [activity("a"), activity("b", 2, "a")]})

    def test_tax_lot_dependencies_are_rejected_without_rebuilding_lots(self):
        p = {"activities": [activity("a")], "tax_lots": [{"id": "lot", "acquisition_activity_id": "a"}]}
        with self.assertRaisesRegex(ValueError, "lot"):
            validate_activity_import(p, {"activities": [activity("b", 2, "a")]})

    def test_a_batch_cannot_correct_and_overwrite_the_original(self):
        for incoming in ([activity("b", 2, "a"), activity("a", 99)], [activity("a", 99), activity("b", 2, "a")]):
            p = {"activities": [activity("a")]}
            before = copy.deepcopy(p)
            with self.subTest(incoming=incoming), self.assertRaises(ValueError):
                merge_activities(p, {"activities": incoming})
            self.assertEqual(p, before)

    def test_incoming_lot_cannot_depend_on_a_superseded_activity(self):
        p = {"activities": [activity("a")]}
        with self.assertRaisesRegex(ValueError, "lot"):
            validate_activity_import(p, {"activities": [activity("b", 2, "a")], "tax_lots": [{"id": "new-lot", "acquisition_activity_id": "a"}]})

    def test_cancellation_removes_original_cashflow_from_calculations(self):
        from rikdom.performance import extract_external_cashflows

        original = {**activity("a"), "event_type": "contribution", "money": {"amount": 100, "currency": "EUR"}}
        cancelled = {**activity("cancel", 1, "a"), "event_type": "contribution", "status": "cancelled", "money": {"amount": 100, "currency": "EUR"}}
        flows, _ = extract_external_cashflows([original, cancelled], "EUR")
        self.assertEqual(flows, [])
        self.assertEqual(original["status"], "posted")


if __name__ == "__main__":
    unittest.main()
