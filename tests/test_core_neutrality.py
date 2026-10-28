import copy
import unittest

from rikdom.aggregate import aggregate_portfolio
from rikdom.plugins import build_import_diff, merge_holdings
from rikdom.fx import ensure_snapshot_fx_lock
from rikdom.reconciliation.reports import render_holding_trust_json


class CoreNeutralityTests(unittest.TestCase):
    def test_instrument_key_cannot_collapse_distinct_accounts(self):
        old = {"id": "a", "account_id": "account-a", "metadata": {"canonical_key": "opaque:instrument"}}
        incoming = {"id": "b", "account_id": "account-b", "metadata": {"canonical_key": "opaque:instrument"}}
        candidate = {"holdings": [copy.deepcopy(old)]}
        preview = build_import_diff(candidate, {"holdings": [incoming]}, collapse_canonical=True)
        merged, counts = merge_holdings(candidate, {"holdings": [incoming]}, collapse_canonical=True)
        self.assertEqual([h["account_id"] for h in merged["holdings"]], ["account-a", "account-b"])
        self.assertEqual(counts.collapsed, 0)
        self.assertEqual(preview["summary"]["holdings"]["create"], 1)

    def test_ambiguous_positions_are_not_arbitrarily_collapsed(self):
        entries = [{"id": name, "account_id": "same", "metadata": {"canonical_key": "opaque:x"}} for name in ("a", "b")]
        merged, counts = merge_holdings({"holdings": entries}, {"holdings": [{**entries[0], "id": "c"}]}, collapse_canonical=True)
        self.assertEqual(len(merged["holdings"]), 3)
        self.assertEqual(counts.collapsed, 0)

    def test_currency_is_required_instead_of_assuming_usd(self):
        with self.assertRaisesRegex(ValueError, "base_currency"):
            aggregate_portfolio({"holdings": []})

    def test_fx_lock_does_not_assume_a_reporting_currency(self):
        with self.assertRaisesRegex(ValueError, "base_currency"):
            ensure_snapshot_fx_lock({"holdings": []}, fx_history_path="/nonexistent", snapshot_timestamp="2026-01-01T00:00:00Z")

    def test_calculations_do_not_round_currency_to_two_decimals(self):
        p = {"settings": {"base_currency": "KWD"}, "asset_type_catalog": [{"id": "asset", "asset_class": "other"}], "holdings": [{"id": "a", "asset_type_id": "asset", "market_value": {"amount": 1.2345, "currency": "KWD"}}]}
        result = aggregate_portfolio(p)
        self.assertEqual(result.total_value_base, 1.2345)
        self.assertEqual(result.by_asset_class["other"], 1.2345)
        report = render_holding_trust_json(result, portfolio_id="test", generated_at="2026-01-01T00:00:00Z")
        self.assertEqual(report["invariant"]["sum_holdings_base"], 1.2345)

    def test_nonfinite_money_is_excluded_instead_of_contaminating_totals(self):
        p = {"settings": {"base_currency": "EUR"}, "holdings": [{"id": "bad", "market_value": {"amount": float("nan"), "currency": "EUR"}}]}
        result = aggregate_portfolio(p)
        self.assertEqual(result.total_value_base, 0)
        self.assertEqual(result.trust_records[0].excluded_reason, "invalid_money")


if __name__ == "__main__":
    unittest.main()
