from __future__ import annotations

import json
import unittest
from pathlib import Path

from rikdom.aggregate import aggregate_portfolio
from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities, merge_holdings
from rikdom.storage import load_json


class CharlesSchwabPluginTests(unittest.TestCase):
    def test_plugin_parses_taxable_mixed_fixture(self) -> None:
        payload = run_import_pipeline(
            plugin_name="charles-schwab",
            plugins_dir="plugins",
            input_path="plugins/charles-schwab/fixtures/taxable-mixed/input.csv",
        )

        self.assertEqual(payload["provider"], "charles-schwab")
        self.assertEqual(payload["base_currency"], "USD")
        self.assertEqual(len(payload["holdings"]), 3)
        self.assertEqual(len(payload["activities"]), 5)

        fee = next(a for a in payload["activities"] if a["event_type"] == "fee")
        self.assertEqual(fee["money"], {"amount": -5.0, "currency": "USD"})

        buy = next(a for a in payload["activities"] if a["event_type"] == "buy")
        self.assertEqual(buy["money"]["amount"], -760.0)
        self.assertEqual(buy["instrument"]["ticker"], "MSFT")

        accounts = payload["metadata"]["accounts"]
        self.assertEqual(accounts[0]["account_number"], "ABCD-1234")

    def test_plugin_import_is_idempotent_for_repeated_statement(self) -> None:
        payload = run_import_pipeline(
            plugin_name="charles-schwab",
            plugins_dir="plugins",
            input_path="plugins/charles-schwab/fixtures/ira-income/input.csv",
        )

        portfolio: dict = {"holdings": [], "activities": []}

        _, holdings_counts_first = merge_holdings(portfolio, payload)
        _, activities_counts_first = merge_activities(portfolio, payload)
        self.assertEqual(
            (holdings_counts_first.inserted, holdings_counts_first.updated), (2, 0)
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
            (0, 0, 2),
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
                plugin_name="charles-schwab",
                plugins_dir="plugins",
                input_path="plugins/charles-schwab/fixtures/invalid-amount/input.csv",
            )

    def test_e2e_workspace_exercises_multi_currency_import_and_aggregation(
        self,
    ) -> None:
        workspace = Path("tests/e2e-data/charles-schwab")
        payload = run_import_pipeline(
            plugin_name="charles-schwab",
            plugins_dir="plugins",
            input_path=str(workspace / "input-taxable-mixed.csv"),
        )

        self.assertEqual(payload["base_currency"], "USD")
        eur_holding = next(
            holding
            for holding in payload["holdings"]
            if holding["id"] == "schwab:euro-4321:pos:sap"
        )
        self.assertEqual(
            eur_holding["market_value"], {"amount": 1400.0, "currency": "EUR"}
        )
        eur_cash = next(
            holding
            for holding in payload["holdings"]
            if holding["id"] == "schwab:euro-4321:cash:eur"
        )
        self.assertEqual(eur_cash["market_value"], {"amount": 100.0, "currency": "EUR"})
        eur_buy = next(
            activity
            for activity in payload["activities"]
            if activity["id"] == "schwab-txn-euro-4321-TXN-EUR-1001"
        )
        self.assertEqual(eur_buy["money"], {"amount": -280.0, "currency": "EUR"})
        self.assertEqual(eur_buy["fees"], {"amount": 2.0, "currency": "EUR"})

        portfolio = load_json(workspace / "portfolio.json")
        portfolio["holdings"] = payload["holdings"]
        portfolio["activities"] = payload["activities"]
        with (workspace / "fx_rates.jsonl").open(encoding="utf-8") as f:
            fx_rates = {
                row["quote_currency"]: row["rate_to_base"]
                for row in (json.loads(line) for line in f if line.strip())
                if row["base_currency"] == "USD"
            }

        aggregate = aggregate_portfolio(
            portfolio, strict=True, fx_rates_to_base=fx_rates
        )
        self.assertEqual(aggregate.base_currency, "USD")
        self.assertEqual(aggregate.errors, [])
        self.assertEqual(aggregate.total_value_base, 13770.44)

    def test_e2e_workspace_rejects_malformed_transaction_fees(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid fees"):
            run_import_pipeline(
                plugin_name="charles-schwab",
                plugins_dir="plugins",
                input_path="tests/e2e-data/charles-schwab/input-invalid-fees.csv",
            )

    def test_e2e_workspace_rejects_buy_without_quantity(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "missing required quantity for buy/sell"
        ):
            run_import_pipeline(
                plugin_name="charles-schwab",
                plugins_dir="plugins",
                input_path="tests/e2e-data/charles-schwab/input-invalid-buy-quantity.csv",
            )


if __name__ == "__main__":
    unittest.main()
