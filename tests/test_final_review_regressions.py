import copy
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from rikdom.activities import check_financial_contract, validate_activity_import
from rikdom.aggregate import aggregate_portfolio
from rikdom.cli import main
from rikdom.import_preflight import build_preflight_report
from rikdom.performance import compute_performance
from rikdom.plugins import merge_activities
from rikdom.storage import save_json, append_jsonl, load_json
from tests.test_activity_corrections import activity
from tests.test_import_diagnostics import event, diagnostics
from tests.test_quantity_coverage import portfolio


ROOT = Path(__file__).resolve().parents[1]


class FinalReviewRegressions(unittest.TestCase):
    def test_reviewed_import_and_original_export_remain_replayable(self):
        p = {"holdings": [], "activities": [event("a")]}
        b = event("b", "doc-b")
        b["metadata"]["rikdom_source_identity"]["kind"] = "reviewed"
        resolution = {"scope": "opaque-account", "document_fingerprint": "doc-b", "existing_activity_ids": ["a"], "new_activity_ids": ["b"], "reason": "Verified"}
        payload = {"activities": [event("a"), b], "metadata": {"rikdom_import_diagnostics": {**diagnostics("doc-b"), "identity_resolution": resolution}}}
        self.assertTrue(build_preflight_report(p, payload)["ok"])
        merge_activities(p, payload)
        self.assertTrue(build_preflight_report(p, payload)["ok"])
        self.assertTrue(build_preflight_report(p, {"activities": [event("a")]})["ok"])
        changed = copy.deepcopy(payload)
        changed["activities"][1]["quantity"] = 999
        self.assertFalse(build_preflight_report(p, changed)["ok"])

    def test_conflicting_isin_cannot_match_through_ticker(self):
        p = portfolio()
        p["holdings"][0]["identifiers"]["isin"] = "JP1111111111"
        p["activities"][0].pop("holding_id")
        p["activities"][0]["instrument"]["isin"] = "JP2222222222"
        self.assertEqual(aggregate_portfolio(p, fx_rates_to_base={"JPY": .006}).quantity_reconciliation[0]["status"], "not_computable")

    def test_future_legacy_contract_is_not_calculated(self):
        with self.assertRaisesRegex(ValueError, "1.999.0"):
            check_financial_contract({"schema_version": "1.999.0"})

    def test_later_lot_import_cannot_reference_superseded_event(self):
        p = {"schema_version": "2.0.0", "activities": [activity("a"), activity("b", 2, "a")]}
        with self.assertRaisesRegex(ValueError, "lot"):
            validate_activity_import(p, {"tax_lots": [{"id": "late-lot", "acquisition_activity_id": "a"}]})

    def test_performance_preserves_non_two_decimal_currency_values(self):
        snapshots = [{"timestamp": "2026-01-01T00:00:00Z", "totals": {"portfolio_value_base": 1.2345}}, {"timestamp": "2026-02-01T00:00:00Z", "totals": {"portfolio_value_base": 2.3456}}]
        result = compute_performance(snapshots, [], base_currency="KWD")
        self.assertEqual(result.start_value_base, 1.2345)
        self.assertEqual(result.end_value_base, 2.3456)

    def test_reconcile_preserves_cached_effective_fx_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_json(root / "portfolio.json", portfolio())
            append_jsonl(root / "fx_rates.jsonl", {"base_currency": "EUR", "quote_currency": "JPY", "as_of_date": "2026-01-31", "rate_to_base": .006, "source": "local-authority"})
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main(["reconcile", "--data-dir", str(root), "--out-root", str(root / "out")])
            self.assertEqual(code, 0)
            trust = load_json(root / "out/reports/holding_trust.json")
            self.assertEqual(trust["fx_context"]["rate_dates"]["JPY"], "2026-01-31")
            self.assertEqual(trust["holdings"][0]["fx_provider"], "local-authority")

    def test_correction_command_works_without_repository_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            shutil.copytree(ROOT / "src/rikdom", site / "rikdom", ignore=shutil.ignore_patterns("__pycache__"))
            p = load_json(ROOT / "tests/fixtures/portfolio.json")
            p["activities"] = [activity("a")]
            save_json(root / "data/portfolio.json", p)
            save_json(root / "replacement.json", activity("new", 2))
            env = {**os.environ, "PYTHONPATH": str(site)}
            result = subprocess.run([sys.executable, "-m", "rikdom", "activity", "correct", "a", "--input", str(root / "replacement.json"), "--reason", "Verified", "--data-dir", str(root / "data"), "--plugins-dir", str(ROOT / "plugins")], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(load_json(root / "data/portfolio.json")["schema_version"], p["schema_version"])
