import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from rikdom.cli import main
from rikdom.storage import load_json, save_json, append_jsonl
from test_quantity_coverage import portfolio as declared_portfolio
from test_import_diagnostics import event


ROOT = Path(__file__).resolve().parents[1]


class ImportTrustWorkflowTests(unittest.TestCase):
    def test_local_import_repeat_review_correction_reconcile_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, out = root / "data", root / "out"
            path = data / "portfolio.json"
            p = load_json(ROOT / "tests/fixtures/portfolio.json")
            declared = declared_portfolio()
            p.update(settings=declared["settings"], holdings=[], activities=[], extensions={})
            save_json(path, p)
            append_jsonl(data / "fx_rates.jsonl", {"base_currency": "EUR", "quote_currency": "JPY", "as_of_date": "2026-01-31", "rate_to_base": .006123, "source": "local-fixture"})
            declaration = declared["extensions"]["rikdom_import_diagnostics"]["statements"]["doc"]
            declaration["document_fingerprint"] = "doc-a"
            a = declared["activities"][0]
            a.update(idempotency_key="a", money={"amount": 100, "currency": "JPY"}, metadata=event("a")["metadata"])
            a["metadata"]["rikdom_source_identity"]["scope"] = "account-jp"
            source = {"provider": "fixture", "generated_at": "2026-02-01T00:00:00Z", "holdings": declared["holdings"], "activities": [a], "metadata": {"rikdom_import_diagnostics": declaration}}
            statement = root / "statement.json"
            save_json(statement, source)

            def run(*args):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main([*args, "--data-dir", str(data), "--out-root", str(out), "--plugins-dir", str(ROOT / "plugins")])
                return code, stdout.getvalue(), stderr.getvalue()

            args = ("import-statement", "--plugin", "normalized-statement-json", "--input", str(statement), "--ingested-at", "2026-02-01T00:00:00Z")
            before = path.read_bytes()
            code, result, errors = run(*args, "--dry-run", "--reconcile")
            self.assertEqual(code, 0, errors)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(out.exists())
            self.assertFalse((data / "import_log.jsonl").exists())
            self.assertEqual(json.loads(result)["reconciliation"]["quantity_summary"]["matched"], 1)
            code, result, errors = run(*args, "--write", "--reconcile")
            self.assertEqual(code, 0, errors)
            artifacts = json.loads(result)["reconciliation"]["artifacts"]
            self.assertEqual(len(artifacts), 4)
            self.assertTrue(all(Path(a["path"]).is_file() for a in artifacts))
            code, result, errors = run(*args, "--write")
            self.assertEqual(code, 0, errors)
            self.assertEqual(json.loads(result)["activities"]["skipped"], 1)
            self.assertEqual(len(load_json(path)["extensions"]["rikdom_import_diagnostics"]["statements"]), 1)

            original = copy.deepcopy(load_json(path)["activities"][0])
            b = copy.deepcopy(original)
            b.update(id="b", idempotency_key="b")
            b["metadata"]["rikdom_source_identity"]["document_fingerprint"] = "doc-b"
            overlap = {"provider": "fixture", "generated_at": source["generated_at"], "activities": [b], "metadata": {"rikdom_import_diagnostics": {"version": 1, "document_fingerprint": "doc-b", "history_coverage": [], "unsupported_events": []}}}
            save_json(statement, overlap)
            before, log_before = path.read_bytes(), (data / "import_log.jsonl").read_bytes()
            self.assertEqual(run(*args, "--write")[0], 1)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual((data / "import_log.jsonl").read_bytes(), log_before)
            b["metadata"]["rikdom_source_identity"]["kind"] = "reviewed"
            overlap["activities"] = [original, b]
            overlap["metadata"]["rikdom_import_diagnostics"]["identity_resolution"] = {"scope": "account-jp", "document_fingerprint": "doc-b", "existing_activity_ids": ["a"], "new_activity_ids": ["b"], "reason": "Confirmed a second identical execution"}
            save_json(statement, overlap)
            code, _, errors = run(*args, "--write")
            self.assertEqual(code, 0, errors)
            self.assertEqual(len(load_json(path)["activities"]), 2)

            replacement = copy.deepcopy(original)
            replacement.update(id="correction", quantity=1)
            replacement.pop("idempotency_key")
            replacement["metadata"].pop("rikdom_source_identity")
            replacement_path = root / "correction.json"
            save_json(replacement_path, replacement)
            code, _, errors = run("activity", "correct", "a", "--input", str(replacement_path), "--reason", "Confirmed original quantity", "--write")
            self.assertEqual(code, 0, errors)
            current = load_json(path)
            self.assertEqual(current["schema_version"], "2.0.0")
            self.assertEqual(current["activities"][0], original)
            self.assertEqual(len(current["activities"]), 3)
            code, _, errors = run("viz", "--plugin", "quarto-portfolio-report", "--include-current")
            self.assertEqual(code, 0, errors)
            payload = load_json(out / "quarto-input.json")
            self.assertAlmostEqual(payload["sections"]["current_valuation"]["total_value_base"], 1.2246)
            self.assertTrue((out / "dashboard.html").is_file())
            self.assertTrue((out / "portfolio-report.html").is_file())


if __name__ == "__main__":
    unittest.main()
