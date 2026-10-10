from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.cli import main


class FiiHistoryImportCliTests(unittest.TestCase):
    def test_normalized_history_imports_lots_and_reimport_is_idempotent(self) -> None:
        portfolio = {
            "schema_version": "1.5.0",
            "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
            "profile": {"portfolio_id": "test", "owner_kind": "person", "display_name": "Test"},
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "reit", "label": "FII", "asset_class": "reits"}],
            "holdings": [{
                "id": "fii", "asset_type_id": "reit", "label": "Test FII", "quantity": 10,
                "market_value": {"amount": 1100, "currency": "BRL"},
            }],
        }
        statement = {
            "provider": "recovered-history", "generated_at": "2026-10-09T00:00:00Z",
            "activities": [{
                "id": "buy", "event_type": "buy", "effective_at": "2025-01-01T00:00:00Z",
                "holding_id": "fii", "quantity": 10,
                "money": {"amount": 1000, "currency": "BRL"}, "source_ref": "note#page=1",
            }],
            "tax_lots": [{
                "id": "lot", "holding_id": "fii", "acquired_at": "2025-01-01T00:00:00Z",
                "quantity": 10, "cost_basis": {"amount": 1000, "currency": "BRL"},
                "acquisition_activity_id": "buy", "provenance": {"source_ref": "note#page=1"},
            }],
        }
        with TemporaryDirectory() as tmp:
            path, source, log = (Path(tmp) / n for n in ("portfolio.json", "statement.json", "log.jsonl"))
            path.write_text(json.dumps(portfolio), encoding="utf-8")
            source.write_text(json.dumps(statement), encoding="utf-8")
            args = [
                "import-statement", "--plugin", "normalized-statement-json", "--plugins-dir", "plugins",
                "--portfolio", str(path), "--input", str(source), "--import-log", str(log),
            ]
            before = path.read_bytes()
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = main([*args, "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertEqual(path.read_bytes(), before)
            output, err = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(err):
                rc = main([*args, "--write", "--import-run-id", "first"])
            self.assertEqual(rc, 0, err.getvalue())
            imported = json.loads(path.read_text())
            self.assertEqual(len(imported["tax_lots"]), 1)
            self.assertEqual(imported["tax_lots"][0]["cost_basis"]["amount"], 1000)
            self.assertEqual(imported["tax_lots"][0]["provenance"]["source_system"], "recovered-history")
            self.assertEqual(json.loads(output.getvalue())["tax_lots"]["inserted"], 1)
            first = path.read_bytes()
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = main([*args, "--write", "--import-run-id", "second"])
            self.assertEqual(rc, 0)
            self.assertEqual(path.read_bytes(), first)

    def test_malformed_history_is_rejected_before_portfolio_write(self) -> None:
        with TemporaryDirectory() as tmp:
            path, source = Path(tmp) / "portfolio.json", Path(tmp) / "statement.json"
            path.write_text(json.dumps({"holdings": []}), encoding="utf-8")
            before = path.read_bytes()
            source.write_text(json.dumps({
                "provider": "recovered", "generated_at": "2026-10-09T00:00:00Z",
                "activities": [{"id": "a", "event_type": "amortization", "effective_at": "bad-date"}],
            }), encoding="utf-8")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = main([
                    "import-statement", "--plugin", "normalized-statement-json", "--plugins-dir", "plugins",
                    "--portfolio", str(path), "--input", str(source), "--write", "--import-log", str(Path(tmp)/"log"),
                ])
            self.assertEqual(rc, 1)
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("effective_at", err.getvalue())


if __name__ == "__main__":
    unittest.main()
