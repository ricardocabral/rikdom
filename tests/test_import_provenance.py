from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rikdom.cli import main as cli_main


SAMPLE_PORTFOLIO = {
    "schema_version": "1.2.0",
    "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
    "profile": {
        "portfolio_id": "test",
        "owner_kind": "person",
        "display_name": "Test",
    },
    "settings": {"base_currency": "USD"},
    "asset_type_catalog": [
        {"id": "stock", "label": "Stock", "asset_class": "stocks"},
        {"id": "reit", "label": "REIT", "asset_class": "reits"},
    ],
    "holdings": [],
    "activities": [],
}


class ImportProvenanceTests(unittest.TestCase):
    def _run_import(self, portfolio_path: Path, log_path: Path, run_id: str) -> None:
        rc = cli_main(
            [
                "import-statement",
                "--plugin",
                "csv-generic",
                "--plugins-dir",
                "plugins",
                "--input",
                "tests/fixtures/sample_statement.csv",
                "--portfolio",
                str(portfolio_path),
                "--import-log",
                str(log_path),
                "--import-run-id",
                run_id,
                "--ingested-at",
                "2026-04-20T00:00:00Z",
                "--write",
            ]
        )
        self.assertEqual(rc, 0)

    def test_stamps_provenance_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio_path = root / "portfolio.json"
            log_path = root / "import_log.jsonl"
            portfolio_path.write_text(json.dumps(SAMPLE_PORTFOLIO), encoding="utf-8")

            self._run_import(portfolio_path, log_path, run_id="run-1")
            first = portfolio_path.read_bytes()

            holdings = json.loads(first)["holdings"]
            self.assertTrue(holdings)
            prov = holdings[0]["provenance"]
            self.assertEqual(prov["import_run_id"], "run-1")
            self.assertEqual(prov["ingested_at"], "2026-04-20T00:00:00Z")
            self.assertEqual(prov["source_system"], "csv-generic")
            self.assertTrue(prov["idempotency_key"])

            activities = json.loads(first)["activities"]
            self.assertTrue(activities)
            self.assertEqual(activities[0]["import_run_id"], "run-1")
            self.assertEqual(activities[0]["ingested_at"], "2026-04-20T00:00:00Z")

            self._run_import(portfolio_path, log_path, run_id="run-2")
            second = portfolio_path.read_bytes()
            self.assertEqual(
                first,
                second,
                "Re-importing the same statement must not modify portfolio.json",
            )

            log_entries = [
                json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line
            ]
            self.assertEqual(len(log_entries), 2)
            self.assertEqual(log_entries[0]["import_run_id"], "run-1")
            self.assertEqual(log_entries[0]["holdings"]["inserted"], 2)
            self.assertEqual(log_entries[0]["activities"]["inserted"], 3)
            self.assertEqual(log_entries[1]["import_run_id"], "run-2")
            self.assertEqual(
                (
                    log_entries[1]["holdings"]["inserted"],
                    log_entries[1]["holdings"]["updated"],
                    log_entries[1]["holdings"]["skipped"],
                ),
                (0, 0, 2),
            )
            self.assertEqual(
                (
                    log_entries[1]["activities"]["inserted"],
                    log_entries[1]["activities"]["updated"],
                    log_entries[1]["activities"]["skipped"],
                ),
                (0, 0, 3),
            )


if __name__ == "__main__":
    unittest.main()
