from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities, merge_holdings


class FidelityPluginTests(unittest.TestCase):
    def _parse_rows(self, rows: list[dict[str, str]]) -> dict:
        fieldnames = [
            "record_type",
            "account_number",
            "account_name",
            "account_type",
            "statement_date",
            "currency",
            "security_type",
            "symbol",
            "description",
            "cusip",
            "quantity",
            "market_value",
            "cash_balance",
            "date",
            "action",
            "amount",
            "fees",
            "reference_id",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "statement.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            return run_import_pipeline(
                plugin_name="fidelity",
                plugins_dir="plugins",
                input_path=str(path),
            )

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

    def test_duplicate_reference_id_falls_back_to_digest_id(self) -> None:
        payload = self._parse_rows(
            [
                {
                    "record_type": "account",
                    "account_number": "FID-DUP-1",
                    "account_name": "Brokerage",
                    "account_type": "Taxable",
                    "statement_date": "2026-03-31",
                    "currency": "USD",
                },
                {
                    "record_type": "transaction",
                    "account_number": "FID-DUP-1",
                    "currency": "USD",
                    "date": "03/01/2026",
                    "action": "Dividend",
                    "description": "Original dividend",
                    "amount": "10.00",
                    "reference_id": "DUP-REF",
                },
                {
                    "record_type": "transaction",
                    "account_number": "FID-DUP-1",
                    "currency": "USD",
                    "date": "03/01/2026",
                    "action": "Dividend",
                    "description": "Corrected dividend",
                    "amount": "12.00",
                    "reference_id": "DUP-REF",
                },
            ]
        )

        activities = payload["activities"]
        self.assertEqual(len(activities), 2)
        self.assertEqual(len({activity["id"] for activity in activities}), 2)
        self.assertEqual(activities[0]["id"], "fidelity-txn-fid-dup-1-DUP-REF")
        self.assertNotEqual(activities[1]["id"], "fidelity-txn-fid-dup-1-DUP-REF")
        self.assertEqual(activities[1]["metadata"]["duplicate_reference_id"], "DUP-REF")

    def test_activity_type_does_not_treat_generic_received_or_sent_as_transfer(
        self,
    ) -> None:
        payload = self._parse_rows(
            [
                {
                    "record_type": "account",
                    "account_number": "FID-ACT-1",
                    "account_name": "Brokerage",
                    "account_type": "Taxable",
                    "statement_date": "2026-03-31",
                    "currency": "USD",
                },
                {
                    "record_type": "transaction",
                    "account_number": "FID-ACT-1",
                    "currency": "USD",
                    "date": "03/02/2026",
                    "action": "Cash received from broker",
                    "description": "Ambiguous broker cash movement",
                    "amount": "5.00",
                    "reference_id": "AMB-1",
                },
                {
                    "record_type": "transaction",
                    "account_number": "FID-ACT-1",
                    "currency": "USD",
                    "date": "03/03/2026",
                    "action": "Consent notice settlement",
                    "description": "Contains sent as part of another word",
                    "amount": "6.00",
                    "reference_id": "AMB-2",
                },
            ]
        )

        self.assertEqual(
            [activity["event_type"] for activity in payload["activities"]],
            ["other", "other"],
        )

    def test_transaction_missing_currency_uses_account_currency(self) -> None:
        payload = self._parse_rows(
            [
                {
                    "record_type": "account",
                    "account_number": "FID-EUR-1",
                    "account_name": "International Brokerage",
                    "account_type": "Taxable",
                    "statement_date": "2026-03-31",
                    "currency": "EUR",
                },
                {
                    "record_type": "transaction",
                    "account_number": "FID-EUR-1",
                    "date": "03/04/2026",
                    "action": "Interest",
                    "description": "Monthly interest",
                    "amount": "7.00",
                    "reference_id": "EUR-1",
                },
            ]
        )

        self.assertEqual(payload["base_currency"], "EUR")
        self.assertEqual(payload["activities"][0]["money"]["currency"], "EUR")

    def test_plugin_rejects_invalid_amount_fixture(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid amount"):
            run_import_pipeline(
                plugin_name="fidelity",
                plugins_dir="plugins",
                input_path="plugins/fidelity/fixtures/invalid-amount/input.csv",
            )


if __name__ == "__main__":
    unittest.main()
