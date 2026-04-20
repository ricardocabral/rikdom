from __future__ import annotations

import importlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rikdom.plugin_engine.errors import PluginEngineError
from rikdom.plugin_engine.pipeline import run_storage_sync_pipeline


class DuckDBStoragePluginTests(unittest.TestCase):
    def test_duckdb_storage_sync_creates_db_and_persists_rows(self) -> None:
        if importlib.util.find_spec("duckdb") is None:
            self.skipTest("duckdb is not installed in the test environment")

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "rikdom.duckdb")
            report = run_storage_sync_pipeline(
                plugin_name="duckdb-storage",
                plugins_dir="plugins",
                portfolio_path="data-sample/portfolio.json",
                snapshots_path="data-sample/snapshots.jsonl",
                options={"db_path": db_path},
            )

            self.assertIn("rows_written", report)
            self.assertEqual(report["rows_written"]["portfolio_header"], 1)
            self.assertEqual(report["rows_written"]["holdings"], 6)
            self.assertEqual(report["rows_written"]["snapshots"], 4)
            self.assertEqual(report["db_path"], db_path)
            self.assertEqual(len(report["source_hash_portfolio"]), 64)
            self.assertEqual(len(report["source_hash_snapshots"]), 64)
            self.assertTrue(Path(db_path).exists())

            import duckdb

            conn = duckdb.connect(db_path)
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM portfolio_header").fetchone()[0], 1
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0], 6
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 4
                )
                meta = dict(
                    conn.execute(
                        "SELECT key, value FROM _rikdom_meta WHERE key IN "
                        "('source_hash_portfolio', 'source_hash_snapshots')"
                    ).fetchall()
                )
                self.assertEqual(meta.get("source_hash_portfolio"), report["source_hash_portfolio"])
                self.assertEqual(meta.get("source_hash_snapshots"), report["source_hash_snapshots"])
            finally:
                conn.close()

    def test_duckdb_storage_sync_overwrites_previous_mirror_data(self) -> None:
        if importlib.util.find_spec("duckdb") is None:
            self.skipTest("duckdb is not installed in the test environment")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = str(tmp / "rikdom.duckdb")
            portfolio_path = tmp / "portfolio.json"
            snapshots_path = tmp / "snapshots.jsonl"

            portfolio_payload = {
                "schema_version": "1.2.0",
                "profile": {
                    "portfolio_id": "test-portfolio",
                    "owner_kind": "person",
                    "display_name": "Test Portfolio",
                    "country": "BR",
                    "created_at": "2026-04-20T00:00:00Z",
                },
                "settings": {"base_currency": "BRL", "timezone": "America/Sao_Paulo"},
                "holdings": [
                    {
                        "id": "h-test-1",
                        "asset_type_id": "stock",
                        "label": "Test Holding",
                        "identifiers": {"ticker": "TEST3"},
                        "quantity": 10,
                        "market_value": {"amount": 1000, "currency": "BRL"},
                        "as_of": "2026-04-20T00:00:00Z",
                    }
                ],
            }
            portfolio_path.write_text(json.dumps(portfolio_payload), encoding="utf-8")
            snapshots_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-20T23:59:59Z",
                        "base_currency": "BRL",
                        "totals": {"portfolio_value_base": 1000},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            run_storage_sync_pipeline(
                plugin_name="duckdb-storage",
                plugins_dir="plugins",
                portfolio_path="data-sample/portfolio.json",
                snapshots_path="data-sample/snapshots.jsonl",
                options={"db_path": db_path},
            )
            report = run_storage_sync_pipeline(
                plugin_name="duckdb-storage",
                plugins_dir="plugins",
                portfolio_path=str(portfolio_path),
                snapshots_path=str(snapshots_path),
                options={"db_path": db_path},
            )

            self.assertEqual(report["rows_written"]["holdings"], 1)
            self.assertEqual(report["rows_written"]["snapshots"], 1)

            import duckdb

            conn = duckdb.connect(db_path)
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0], 1
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1
                )
                self.assertEqual(
                    conn.execute("SELECT portfolio_id FROM portfolio_header").fetchone()[0],
                    "test-portfolio",
                )
            finally:
                conn.close()

    def test_duckdb_storage_sync_missing_duckdb_dependency_is_actionable(self) -> None:
        original_import_module = importlib.import_module

        def _fake_import_module(name, package=None):
            if name == "duckdb":
                raise ModuleNotFoundError("No module named 'duckdb'")
            return original_import_module(name, package)

        with mock.patch("importlib.import_module", side_effect=_fake_import_module):
            with self.assertRaises(PluginEngineError) as ctx:
                run_storage_sync_pipeline(
                    plugin_name="duckdb-storage",
                    plugins_dir="plugins",
                    portfolio_path="data-sample/portfolio.json",
                    snapshots_path="data-sample/snapshots.jsonl",
                    options={"db_path": "out/rikdom.duckdb"},
                )

        self.assertIn("duckdb Python package is required", str(ctx.exception))
        self.assertIn("pip install duckdb", str(ctx.exception))

    def test_duckdb_storage_sync_returns_row_counts(self) -> None:
        if importlib.util.find_spec("duckdb") is None:
            self.skipTest("duckdb is not installed in the test environment")

        report = run_storage_sync_pipeline(
            plugin_name="duckdb-storage",
            plugins_dir="plugins",
            portfolio_path="data-sample/portfolio.json",
            snapshots_path="data-sample/snapshots.jsonl",
            options={"db_path": "out/rikdom.duckdb"},
        )
        self.assertIn("rows_written", report)
        self.assertIn("holdings", report["rows_written"])
        self.assertIn("db_path", report)
        self.assertEqual(len(report["source_hash_portfolio"]), 64)
        self.assertEqual(len(report["source_hash_snapshots"]), 64)


if __name__ == "__main__":
    unittest.main()
