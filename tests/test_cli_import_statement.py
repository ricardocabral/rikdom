from __future__ import annotations

import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from rikdom.cli import cmd_import_statement
from rikdom.plugin_engine.errors import PluginEngineError


class CliImportStatementTests(unittest.TestCase):
    def test_cmd_import_statement_runs_pluggy_pipeline(self) -> None:
        args = Namespace(
            portfolio="tests/fixtures/portfolio.json",
            plugin="csv-generic",
            input="tests/fixtures/sample_statement.csv",
            plugins_dir="plugins",
            write=False,
            import_log=None,
            import_run_id="run-test",
            ingested_at="2026-04-20T00:00:00Z",
        )
        imported = {
            "holdings": [
                {
                    "id": "new-aapl",
                    "asset_type_id": "stock",
                    "label": "Apple Inc.",
                    "market_value": {"amount": 1000.0, "currency": "USD"},
                }
            ],
            "activities": [
                {
                    "id": "act-aapl-div-2026q1",
                    "event_type": "dividend",
                    "money": {"amount": 1.2, "currency": "USD"},
                    "effective_at": "2026-02-13T00:00:00Z",
                    "idempotency_key": "us-aapl-2026q1-div",
                }
            ],
        }

        with (
            mock.patch("rikdom.cli.load_json", return_value={"holdings": [], "activities": []}),
            mock.patch("rikdom.cli.run_import_pipeline", return_value=imported) as mock_run,
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cmd_import_statement(args)

        self.assertEqual(code, 0)
        mock_run.assert_called_once_with("csv-generic", "plugins", "tests/fixtures/sample_statement.csv")

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["holdings"], {"inserted": 1, "updated": 0, "skipped": 0})
        self.assertEqual(payload["activities"], {"inserted": 1, "updated": 0, "skipped": 0})
        self.assertEqual(payload["import_run_id"], "run-test")
        self.assertEqual(payload["ingested_at"], "2026-04-20T00:00:00Z")
        self.assertEqual(payload["source_system"], "csv-generic")
        self.assertFalse(payload["write"])

    def test_cmd_import_statement_returns_error_for_pipeline_failure(self) -> None:
        args = Namespace(
            portfolio="tests/fixtures/portfolio.json",
            plugin="csv-generic",
            input="tests/fixtures/sample_statement.csv",
            plugins_dir="plugins",
            write=False,
            import_log=None,
            import_run_id="run-test",
            ingested_at="2026-04-20T00:00:00Z",
        )
        with (
            mock.patch("rikdom.cli.load_json", return_value={"holdings": [], "activities": []}),
            mock.patch(
                "rikdom.cli.run_import_pipeline",
                side_effect=PluginEngineError("plugin boom"),
            ),
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = cmd_import_statement(args)

        self.assertEqual(code, 1)
        self.assertIn("Import failed: plugin boom", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
