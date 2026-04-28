from __future__ import annotations

import unittest

from rikdom.aggregate import aggregate_portfolio
from rikdom.reconciliation.reports import (
    HOLDING_TRUST_SCHEMA_URI,
    RECONCILIATION_SCHEMA_URI,
    render_holding_trust_json,
    render_holding_trust_markdown,
    render_reconciliation_json,
    render_reconciliation_markdown,
)


def _portfolio() -> dict:
    return {
        "settings": {"base_currency": "USD"},
        "asset_type_catalog": [
            {"id": "stock", "asset_class": "equity"},
            {"id": "cash", "asset_class": "cash_equivalents"},
        ],
        "holdings": [
            {
                "id": "h-usd",
                "asset_type_id": "stock",
                "quantity": 1,
                "market_value": {"amount": 100.0, "currency": "USD"},
            },
            {
                "id": "h-eur",
                "asset_type_id": "stock",
                "quantity": 1,
                "market_value": {"amount": 50.0, "currency": "EUR"},
            },
            {
                "id": "h-missing",
                "asset_type_id": "stock",
                "quantity": 1,
                "market_value": {"amount": 999.0, "currency": "GBP"},
            },
        ],
        "activities": [],
    }


class HoldingTrustReportTests(unittest.TestCase):
    def test_json_shape_and_invariant_pass(self) -> None:
        result = aggregate_portfolio(_portfolio(), fx_rates_to_base={"EUR": 1.1})
        report = render_holding_trust_json(
            result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z"
        )
        self.assertEqual(report["schema_uri"], HOLDING_TRUST_SCHEMA_URI)
        self.assertEqual(report["portfolio_id"], "p1")
        self.assertEqual(report["base_currency"], "USD")
        self.assertEqual(len(report["holdings"]), 3)
        inv = report["invariant"]
        self.assertTrue(inv["matches"])
        self.assertEqual(inv["total_value_base"], result.total_value_base)
        self.assertIn("h-missing", inv["excluded_holding_ids"])

    def test_markdown_includes_every_holding_and_invariant_status(self) -> None:
        result = aggregate_portfolio(_portfolio(), fx_rates_to_base={"EUR": 1.1})
        report = render_holding_trust_json(
            result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z"
        )
        md = render_holding_trust_markdown(report)
        self.assertIn("h-usd", md)
        self.assertIn("h-eur", md)
        self.assertIn("h-missing", md)
        self.assertIn("fx_missing", md)
        self.assertIn("PASS", md)

    def test_empty_portfolio_produces_matching_invariant(self) -> None:
        result = aggregate_portfolio(
            {
                "settings": {"base_currency": "USD"},
                "asset_type_catalog": [],
                "holdings": [],
                "activities": [],
            }
        )
        report = render_holding_trust_json(
            result, portfolio_id="empty", generated_at="2026-04-28T00:00:00Z"
        )
        self.assertEqual(report["holdings"], [])
        inv = report["invariant"]
        self.assertEqual(inv["sum_holdings_base"], 0.0)
        self.assertEqual(inv["total_value_base"], 0.0)
        self.assertTrue(inv["matches"])
        self.assertEqual(inv["excluded_holding_ids"], [])


class ReconciliationReportTests(unittest.TestCase):
    def test_summary_counts_and_by_code(self) -> None:
        result = aggregate_portfolio(_portfolio())  # no fx → EUR & GBP missing
        report = render_reconciliation_json(
            result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z"
        )
        self.assertEqual(report["schema_uri"], RECONCILIATION_SCHEMA_URI)
        summary = report["summary"]
        self.assertEqual(summary["total"], len(result.findings))
        self.assertEqual(
            summary["warning_count"]
            + summary["error_count"]
            + summary["info_count"],
            summary["total"],
        )
        self.assertIn("RECON_FX_MISSING", summary["by_code"])
        self.assertEqual(summary["by_code"]["RECON_FX_MISSING"], 2)

    def test_markdown_groups_by_severity_and_carries_suggested_fix(self) -> None:
        result = aggregate_portfolio(_portfolio())
        report = render_reconciliation_json(
            result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z"
        )
        md = render_reconciliation_markdown(report)
        self.assertIn("RECON_FX_MISSING", md)
        self.assertIn("Warning", md)
        self.assertIn("Suggested fix", md)

    def test_strict_mode_emits_error_severity_findings(self) -> None:
        result = aggregate_portfolio(_portfolio(), strict=True)
        report = render_reconciliation_json(
            result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z"
        )
        self.assertGreater(report["summary"]["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
