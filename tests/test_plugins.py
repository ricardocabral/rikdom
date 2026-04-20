from __future__ import annotations

import unittest

from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities, merge_holdings


class PluginTests(unittest.TestCase):
    def test_csv_generic_plugin_emits_holdings_and_activities(self) -> None:
        payload = run_import_pipeline(
            plugin_name="csv-generic",
            plugins_dir="plugins",
            input_path="data-sample/sample_statement.csv",
        )
        self.assertEqual(payload["provider"], "csv-generic")
        self.assertEqual(len(payload["holdings"]), 2)
        self.assertEqual(len(payload["activities"]), 3)

        dividend = next(a for a in payload["activities"] if a["id"] == "act-aapl-div-2026q1")
        self.assertEqual(dividend["event_type"], "dividend")
        self.assertEqual(dividend["money"], {"amount": 1.20, "currency": "USD"})
        self.assertEqual(dividend["instrument"]["ticker"], "AAPL")

        reimb = next(a for a in payload["activities"] if a["id"] == "act-broker-reimb-2026-03")
        self.assertEqual(reimb["event_type"], "reimbursement")

    def test_merge_activities_is_idempotent_by_idempotency_key(self) -> None:
        portfolio: dict = {"holdings": [], "activities": []}
        imported = {
            "activities": [
                {
                    "id": "a1",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "idempotency_key": "k1",
                    "money": {"amount": 1.0, "currency": "USD"},
                }
            ]
        }

        _, counts = merge_activities(portfolio, imported)
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (1, 0, 0))
        self.assertEqual(portfolio["activities"][0]["status"], "posted")

        _, counts = merge_activities(portfolio, imported)
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (0, 0, 1))
        self.assertEqual(len(portfolio["activities"]), 1)

    def test_merge_holdings_ignores_missing_holdings_key(self) -> None:
        portfolio: dict = {"holdings": []}
        _, counts = merge_holdings(portfolio, {"activities": []})
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
