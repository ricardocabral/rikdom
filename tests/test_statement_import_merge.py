from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from rikdom.plugins import build_import_diff, merge_holdings


class StatementImportMergeTests(unittest.TestCase):
    def holding(self):
        return {
            "id": "h", "asset_type_id": "fund", "label": "Synthetic fund",
            "market_value": {"amount": 120, "currency": "BRL"},
            "as_of": "2026-10-08T23:59:59-03:00",
            "identifiers": {"isin": "SYNTHETIC", "provider_account_id": "test"},
            "instrument_attributes": {"fund_cnpj": "synthetic"},
            "metadata": {"review": {"done": True}},
            "extensions": {"custom": {"audited": True}},
        }

    def test_partial_refresh_keeps_omitted_instrument_and_audit_fields(self):
        existing = self.holding()
        incoming = {k: existing[k] for k in ("id", "asset_type_id", "label", "as_of")}
        incoming["market_value"] = {"amount": 130, "currency": "BRL"}
        incoming["identifiers"] = {"provider_account_id": "test"}
        portfolio, counts = merge_holdings({"holdings": [copy.deepcopy(existing)]}, {"holdings": [incoming]})
        actual = portfolio["holdings"][0]
        self.assertEqual(actual["market_value"]["amount"], 130)
        self.assertEqual(actual["identifiers"]["isin"], "SYNTHETIC")
        self.assertEqual(actual["instrument_attributes"], existing["instrument_attributes"])
        self.assertEqual(actual["extensions"], existing["extensions"])
        self.assertEqual(counts.updated, 1)
        diff = build_import_diff({"holdings": [existing]}, {"holdings": [incoming]})
        self.assertEqual([c["field"] for c in diff["rows"][0]["changes"]], ["market_value.amount"])

    def test_older_backfill_keeps_current_valuation_even_with_timezone_offsets(self):
        existing = self.holding()
        incoming = copy.deepcopy(existing)
        incoming["as_of"] = "2026-10-09T01:00:00Z"
        incoming["market_value"]["amount"] = 90
        portfolio, counts = merge_holdings({"holdings": [copy.deepcopy(existing)]}, {"holdings": [incoming]})
        self.assertEqual(portfolio["holdings"][0], existing)
        self.assertEqual(counts.skipped, 1)
        self.assertEqual(build_import_diff({"holdings": [existing]}, {"holdings": [incoming]})["rows"][0]["operation"], "noop")

    def test_naive_timestamp_does_not_bypass_older_position_protection(self):
        existing = self.holding()
        incoming = copy.deepcopy(existing)
        incoming.update(as_of="2026-01-01T00:00:00", market_value={"amount": 90, "currency": "BRL"})
        merged, counts = merge_holdings({"holdings": [existing]}, {"holdings": [incoming]})
        self.assertEqual(merged["holdings"][0]["market_value"]["amount"], 120)
        self.assertEqual(counts.skipped, 1)

    def test_partial_valuation_retains_omitted_provisions(self):
        existing = self.holding()
        existing["valuation"] = {"net_value": {"amount": 118, "currency": "BRL"}, "tax_provisions": [{"tax_type": "IR", "money": {"amount": 2, "currency": "BRL"}}]}
        incoming = copy.deepcopy(existing)
        incoming["valuation"] = {"unit_price": {"amount": 10, "currency": "BRL"}}
        merged, _ = merge_holdings({"holdings": [existing]}, {"holdings": [incoming]})
        self.assertEqual(merged["holdings"][0]["valuation"]["net_value"]["amount"], 118)
        self.assertEqual(merged["holdings"][0]["valuation"]["tax_provisions"], existing["valuation"]["tax_provisions"])

    def test_statement_observations_are_persisted_and_reimport_is_noop(self):
        from rikdom.plugins import merge_statement_observations

        observation = {"id": "s", "provider": "test", "period_start": "2026-01-01", "period_end": "2026-01-31", "source": {"path": "synthetic.pdf", "sha256": "a" * 64, "page_count": 1}, "sections": [{"name": "Cash", "page": 1, "text": "Synthetic table"}]}
        portfolio = {"holdings": []}
        merged, counts = merge_statement_observations(portfolio, {"statement_observations": [observation]})
        self.assertEqual(merged["statement_observations"], [observation])
        self.assertEqual(counts.inserted, 1)
        _, counts = merge_statement_observations(merged, {"statement_observations": [observation]})
        self.assertEqual(counts.skipped, 1)
        self.assertEqual(len(merged["statement_observations"]), 1)
        partial = copy.deepcopy(observation)
        partial.pop("sections")
        _, counts = merge_statement_observations(merged, {"statement_observations": [partial]})
        self.assertEqual(merged["statement_observations"][0]["sections"], observation["sections"])
        self.assertEqual(counts.skipped, 1)

    def test_preflight_blocks_duplicates_and_malformed_sources_without_crashing(self):
        from rikdom.import_preflight import build_preflight_report

        observation = {"id": "s", "provider": "test", "period_start": "2026-01-01", "period_end": "2026-01-31", "source": {"path": "synthetic.pdf", "sha256": "a" * 64, "page_count": 1}}
        self.assertFalse(build_preflight_report({"holdings": []}, {"statement_observations": [observation, observation]})["ok"])
        malformed = {**observation, "source": None}
        self.assertFalse(build_preflight_report({"holdings": [], "statement_observations": [observation]}, {"statement_observations": [malformed]})["ok"])

    def test_conflicting_source_observation_fails_without_mutation(self):
        from rikdom.plugins import merge_statement_observations

        original = {"id": "s", "provider": "test", "period_start": "2026-01-01", "period_end": "2026-01-31", "source": {"path": "synthetic.pdf", "sha256": "a" * 64, "page_count": 1}}
        portfolio = {"holdings": [], "statement_observations": [original]}
        changed = copy.deepcopy(original)
        changed["source"]["sha256"] = "b" * 64
        before = copy.deepcopy(portfolio)
        with self.assertRaisesRegex(ValueError, "Conflicting statement observation"):
            merge_statement_observations(portfolio, {"statement_observations": [changed]})
        self.assertEqual(portfolio, before)

    def test_cli_persists_observation_only_import_and_reports_noop_on_repeat(self):
        from rikdom.cli import main

        observation = {"id": "s", "provider": "test", "period_start": "2026-01-01", "period_end": "2026-01-31", "source": {"path": "synthetic.pdf", "sha256": "a" * 64, "page_count": 1}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            portfolio = json.loads(Path("tests/fixtures/portfolio.json").read_text())
            portfolio["schema_version"] = "1.7.0"
            (root / "portfolio.json").write_text(json.dumps(portfolio))
            statement = {"provider": "test", "generated_at": "2026-02-01T00:00:00Z", "statement_observations": [observation]}
            (root / "statement.json").write_text(json.dumps(statement))
            args = ["import-statement", "--data-dir", str(root), "--out-root", str(root / "out"), "--plugin", "normalized-statement-json", "--input", str(root / "statement.json"), "--write"]
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
            self.assertEqual(json.loads((root / "portfolio.json").read_text()).get("statement_observations"), [observation])
            self.assertEqual(json.loads(output.getvalue())["dry_run_diff"]["summary"]["statement_observations"]["create"], 1)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(output.getvalue())["statement_observations"]["skipped"], 1)
