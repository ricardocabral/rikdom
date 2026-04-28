from __future__ import annotations

import unittest

from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities, merge_holdings


class FidelityPluginTests(unittest.TestCase):
    def test_plugin_parses_taxable_brokerage_fixture(self) -> None:
        payload = run_import_pipeline(
            plugin_name="fidelity",
            plugins_dir="plugins",
            input_path="plugins/fidelity/fixtures/taxable-brokerage/input.csv",
        )

        self.assertEqual(payload["provider"], "fidelity")
        self.assertEqual(payload["base_currency"], "USD")
        self.assertEqual(payload["metadata"]["input_format"], "csv")
        self.assertEqual(len(payload["holdings"]), 3)
        self.assertEqual(len(payload["activities"]), 5)

        buy = next(a for a in payload["activities"] if a["event_type"] == "buy")
        self.assertEqual(buy["money"], {"amount": -340.0, "currency": "USD"})
        self.assertEqual(buy["instrument"]["ticker"], "AAPL")

        fee = next(a for a in payload["activities"] if a["event_type"] == "fee")
        self.assertEqual(fee["money"], {"amount": -10.0, "currency": "USD"})

        accounts = payload["metadata"]["accounts"]
        self.assertEqual(accounts[0]["account_number"], "FID-123456789")
        self.assertEqual(accounts[0]["account_type"], "Taxable Brokerage")

    def test_plugin_parses_retirement_fixture(self) -> None:
        payload = run_import_pipeline(
            plugin_name="fidelity",
            plugins_dir="plugins",
            input_path="plugins/fidelity/fixtures/retirement-ira/input.csv",
        )

        self.assertEqual(payload["provider"], "fidelity")
        self.assertEqual(len(payload["holdings"]), 3)
        self.assertEqual(len(payload["activities"]), 3)

        contribution = next(
            a for a in payload["activities"] if a["event_type"] == "transfer_in"
        )
        self.assertEqual(contribution["money"], {"amount": 6500.0, "currency": "USD"})

        distribution = next(
            a for a in payload["activities"] if a["event_type"] == "transfer_out"
        )
        self.assertEqual(distribution["money"], {"amount": -500.0, "currency": "USD"})

    def test_plugin_import_is_idempotent_for_repeated_statement(self) -> None:
        payload = run_import_pipeline(
            plugin_name="fidelity",
            plugins_dir="plugins",
            input_path="plugins/fidelity/fixtures/retirement-ira/input.csv",
        )
        portfolio: dict = {"holdings": [], "activities": []}

        _, holdings_counts_first = merge_holdings(portfolio, payload)
        _, activities_counts_first = merge_activities(portfolio, payload)
        self.assertEqual(
            (holdings_counts_first.inserted, holdings_counts_first.updated), (3, 0)
        )
        self.assertEqual(
            (activities_counts_first.inserted, activities_counts_first.updated), (3, 0)
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
            (0, 0, 3),
        )

    def test_plugin_rejects_invalid_amount_fixture(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid amount"):
            run_import_pipeline(
                plugin_name="fidelity",
                plugins_dir="plugins",
                input_path="plugins/fidelity/fixtures/invalid-amount/input.csv",
            )


if __name__ == "__main__":
    unittest.main()
