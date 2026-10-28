from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rikdom.reconciliation import reports

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


class SharedTrustReportTests(unittest.TestCase):
    def test_shared_reports_keep_coverage_quantity_and_actual_fx_context(self):
        result = aggregate_portfolio(_portfolio(), fx_rates_to_base={"EUR": 1.1})
        result.fx_lock = {"base_currency": "USD", "rates_to_base": {"EUR": 1.1},
                          "rate_dates": {"EUR": "2026-04-24"},
                          "sources": {"EUR": "custom-bank"}}
        result.import_diagnostics = {
            "history_coverage": [{"status": "partial", "reasons": ["positions only"]}],
            "unsupported_events": [{"source_ref": "row:7", "reason": "unsupported quantity"}],
        }
        result.quantity_reconciliation = [
            {"holding_id": "h-usd", "status": "matched"},
            {"holding_id": "h-eur", "status": "not_computable"},
        ]
        payloads = reports.build_trust_reports(result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z")
        trust = payloads["holding_trust"]
        recon = payloads["reconciliation"]
        self.assertEqual(trust["fx_context"], result.fx_lock)
        eur = next(h for h in trust["holdings"] if h["holding_id"] == "h-eur")
        self.assertEqual(eur["fx_timestamp"], "2026-04-24")
        self.assertEqual(eur["fx_provider"], "custom-bank")
        self.assertEqual(recon["import_diagnostics"], result.import_diagnostics)
        self.assertEqual(recon["coverage_summary"]["by_status"]["partial"], 1)
        self.assertEqual(recon["coverage_summary"]["unsupported_event_count"], 1)
        self.assertEqual(recon["quantity_summary"]["matched"], 1)
        self.assertEqual(recon["quantity_summary"]["not_computable"], 1)
        self.assertEqual(recon["quantity_reconciliation"], result.quantity_reconciliation)

    def test_invalid_or_incompatible_lock_dates_do_not_become_provenance(self):
        for context in (
            {"base_currency": "USD", "rates_to_base": {"EUR": 1.1}, "rate_dates": {"EUR": "not-a-date"}},
            {"base_currency": "GBP", "rates_to_base": {"EUR": 1.1}, "rate_dates": {"EUR": "2026-04-24"}},
        ):
            with self.subTest(context=context):
                result = aggregate_portfolio(_portfolio(), fx_rates_to_base={"EUR": 1.1})
                result.fx_lock = context
                report = reports.build_trust_reports(result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z")
                eur = next(h for h in report["holding_trust"]["holdings"] if h["holding_id"] == "h-eur")
                self.assertNotIn("fx_timestamp", eur)

    def test_metadata_rate_never_inherits_a_lock_timestamp(self):
        portfolio = _portfolio()
        portfolio["holdings"][1]["metadata"] = {"fx_rate_to_base": 1.2}
        result = aggregate_portfolio(portfolio)
        result.fx_lock = {"base_currency": "USD", "rate_dates": {"EUR": "2026-04-24"}}
        payload = reports.build_trust_reports(result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z")
        eur = next(h for h in payload["holding_trust"]["holdings"] if h["holding_id"] == "h-eur")
        self.assertNotIn("fx_timestamp", eur)
        self.assertNotIn("fx_provider", eur)
        self.assertEqual(payload["reconciliation"]["coverage_summary"]["status"], "unknown")

    def test_writer_preserves_four_existing_formats_and_roundtrips_payloads(self):
        result = aggregate_portfolio(_portfolio())
        payloads = reports.build_trust_reports(result, portfolio_id="p1", generated_at="2026-04-28T00:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = reports.write_trust_reports(payloads, Path(tmp) / "reports")
            self.assertEqual({Path(a["path"]).name for a in artifacts}, {
                "holding_trust.json", "reconciliation.json", "holding_trust.md", "reconciliation.md",
            })
            for key in ("holding_trust", "reconciliation"):
                self.assertEqual(json.loads((Path(tmp) / "reports" / f"{key}.json").read_text()), payloads[key])
            markdown = (Path(tmp) / "reports" / "reconciliation.md").read_text()
            self.assertIn("unknown", markdown)
            self.assertIn("not computable", markdown.lower())
            just_json = reports.write_trust_reports(payloads, Path(tmp) / "json", format="json")
            self.assertEqual(len(just_json), 2)
            self.assertTrue(all(Path(a["path"]).suffix == ".json" for a in just_json))
            with self.assertRaises(ValueError):
                reports.write_trust_reports(payloads, Path(tmp) / "invalid", format="invalid")
            self.assertFalse((Path(tmp) / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
