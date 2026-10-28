import copy
import unittest

from rikdom.aggregate import aggregate_portfolio


def portfolio():
    declaration = {"scope": "account-jp", "account_id": "account-jp", "holding_id": "h", "status": "complete", "event_types": ["buy", "sell"], "from": "2026-01-01", "through": "2026-01-31", "timezone": "Asia/Tokyo", "history_origin": "inception", "opening_quantity": 0, "position_basis": "trade", "effective_at_basis": "trade", "evidence": {"kind": "user_declaration", "source_ref": "reviewed-fixture"}}
    return {"settings": {"base_currency": "EUR"}, "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}], "holdings": [{"id": "h", "label": "Synthetic JP equity", "account_id": "account-jp", "asset_type_id": "stock", "quantity": 2, "as_of": "2026-01-31T20:00:00+09:00", "identifiers": {"ticker": "7203"}, "market_value": {"amount": 200, "currency": "JPY"}}], "activities": [{"id": "a", "account_id": "account-jp", "holding_id": "h", "asset_type_id": "stock", "instrument": {"ticker": "7203"}, "event_type": "buy", "quantity": 2, "status": "posted", "effective_at": "2026-01-02T10:00:00+09:00", "settled_at": "2026-02-02T10:00:00+09:00"}], "extensions": {"rikdom_import_diagnostics": {"version": 1, "statements": {"doc": {"version": 1, "history_coverage": [declaration], "unsupported_events": []}}}}}


class QuantityCoverageTests(unittest.TestCase):
    def test_explicit_trade_coverage_compares_quantity_and_retains_precision(self):
        result = aggregate_portfolio(portfolio(), fx_rates_to_base={"JPY": .006123})
        self.assertEqual(result.quantity_reconciliation[0]["status"], "matched")
        self.assertAlmostEqual(result.total_value_base, 1.2246)

    def test_expired_or_settled_coverage_never_claims_a_match(self):
        for field, value in (("through", "2026-01-30"), ("position_basis", "settled"), ("opening_quantity", 10)):
            p = portfolio()
            p["extensions"]["rikdom_import_diagnostics"]["statements"]["doc"]["history_coverage"][0][field] = value
            self.assertEqual(aggregate_portfolio(p, fx_rates_to_base={"JPY": .006}).quantity_reconciliation[0]["status"], "not_computable")

    def test_later_and_other_account_trades_do_not_change_position(self):
        p = portfolio()
        other = {**p["activities"][0], "id": "other", "account_id": "other-account", "holding_id": "other", "quantity": 50}
        later = {**p["activities"][0], "id": "later", "effective_at": "2026-02-01T10:00:00+09:00", "quantity": 20}
        p["activities"].extend([other, later])
        self.assertEqual(aggregate_portfolio(p, fx_rates_to_base={"JPY": .006}).quantity_reconciliation[0]["ledger_quantity"], 2)

    def test_no_history_is_not_a_successful_reconciliation(self):
        p = copy.deepcopy(portfolio())
        p.pop("extensions")
        self.assertEqual(aggregate_portfolio(p, fx_rates_to_base={"JPY": .006}).quantity_reconciliation[0]["status"], "not_computable")

    def test_explicit_history_exposes_a_real_quantity_mismatch(self):
        p = portfolio()
        p["holdings"][0]["quantity"] = 3
        result = aggregate_portfolio(p, fx_rates_to_base={"JPY": .006})
        self.assertEqual(result.quantity_reconciliation[0]["status"], "mismatched")
        self.assertIn("RECON_QTY_LEDGER_MISMATCH", [f.code for f in result.findings])

    def test_empty_categories_or_pre_inception_movements_are_not_computable(self):
        for field, value in (("event_types", []), ("from", "2026-01-03")):
            p = portfolio()
            p["holdings"][0]["quantity"] = 0
            p["extensions"]["rikdom_import_diagnostics"]["statements"]["doc"]["history_coverage"][0][field] = value
            self.assertEqual(aggregate_portfolio(p, fx_rates_to_base={"JPY": .006}).quantity_reconciliation[0]["status"], "not_computable")

    def test_corporate_action_legs_are_not_silently_ignored(self):
        p = portfolio()
        p["extensions"]["rikdom_import_diagnostics"]["statements"]["doc"]["history_coverage"][0]["event_types"].append("split")
        p["activities"].append({"id": "split", "account_id": "account-jp", "event_type": "split", "effective_at": "2026-01-04T10:00:00+09:00", "corporate_action": {"kind": "split", "legs": [{"holding_id": "h", "quantity_delta": 2}]}})
        self.assertEqual(aggregate_portfolio(p, fx_rates_to_base={"JPY": .006}).quantity_reconciliation[0]["status"], "mismatched")


if __name__ == "__main__":
    unittest.main()
