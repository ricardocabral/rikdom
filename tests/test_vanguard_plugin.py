from __future__ import annotations

import unittest

from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities, merge_holdings


class VanguardPluginTests(unittest.TestCase):
    def test_plugin_parses_etf_heavy_fixture(self) -> None:
        payload = run_import_pipeline(
            plugin_name="vanguard",
            plugins_dir="plugins",
            input_path="plugins/vanguard/fixtures/etf-heavy/input.csv",
        )

        self.assertEqual(payload["provider"], "vanguard")
        self.assertEqual(payload["base_currency"], "USD")
        self.assertEqual(len(payload["holdings"]), 3)
        self.assertEqual(len(payload["activities"]), 5)

        fee = next(a for a in payload["activities"] if a["event_type"] == "fee")
        self.assertEqual(fee["money"], {"amount": -4.0, "currency": "USD"})

        buy = next(a for a in payload["activities"] if a["event_type"] == "buy")
        self.assertEqual(buy["money"]["amount"], -780.0)
        self.assertEqual(buy["instrument"]["ticker"], "VTI")

        accounts = payload["metadata"]["accounts"]
        self.assertEqual(accounts[0]["account_number"], "VG-00112233")

    def test_plugin_import_is_idempotent_for_repeated_statement(self) -> None:
        payload = run_import_pipeline(
            plugin_name="vanguard",
            plugins_dir="plugins",
            input_path="plugins/vanguard/fixtures/mutual-fund-heavy/input.csv",
        )

        portfolio: dict = {"holdings": [], "activities": []}

        _, holdings_counts_first = merge_holdings(portfolio, payload)
        _, activities_counts_first = merge_activities(portfolio, payload)
        self.assertEqual(
            (holdings_counts_first.inserted, holdings_counts_first.updated), (3, 0)
        )
        self.assertEqual(
            (activities_counts_first.inserted, activities_counts_first.updated), (5, 0)
        )

        _, holdings_counts_second = merge_holdings(portfolio, payload)
        _, activities_counts_second = merge_activities(portfolio, payload)
        self.assertEqual(
            (
                holdings_counts_second.inserted,
                holdings_counts_second.updated,
                holdings_counts_second.skipped,
            ),
            (0, 0, 3),
        )
        self.assertEqual(
            (
                activities_counts_second.inserted,
                activities_counts_second.updated,
                activities_counts_second.skipped,
            ),
            (0, 0, 5),
        )

    def test_plugin_rejects_invalid_amount_fixture(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid amount"):
            run_import_pipeline(
                plugin_name="vanguard",
                plugins_dir="plugins",
                input_path="plugins/vanguard/fixtures/invalid-amount/input.csv",
            )


if __name__ == "__main__":
    unittest.main()
