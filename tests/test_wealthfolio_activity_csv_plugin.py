from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.plugin_engine.pipeline import run_import_pipeline


class WealthfolioActivityCsvPluginTests(unittest.TestCase):
    def test_plugin_maps_activity_csv_rows(self) -> None:
        payload = run_import_pipeline(
            plugin_name="wealthfolio_activity_csv",
            plugins_dir="plugins",
            input_path="tests/fixtures/wealthfolio_activities_sample.csv",
        )

        self.assertEqual(payload["provider"], "wealthfolio_activity_csv")
        ids = {a["id"] for a in payload["activities"]}
        self.assertEqual(
            ids,
            {
                "wealthfolio-csv-wf-csv-buy-1",
                "wealthfolio-csv-wf-csv-div-1",
                "wealthfolio-csv-wf-csv-dep-1",
                "wealthfolio-csv-wf-csv-tax-1",
                "wealthfolio-csv-wf-csv-draft-1",
            },
        )

        buy = next(a for a in payload["activities"] if a["id"] == "wealthfolio-csv-wf-csv-buy-1")
        self.assertEqual(buy["event_type"], "buy")
        self.assertEqual(buy["effective_at"], "2026-04-10T15:30:00Z")
        self.assertEqual(buy["money"], {"amount": -1705.0, "currency": "USD"})
        self.assertEqual(buy["fees"], {"amount": 1.5, "currency": "USD"})
        self.assertEqual(buy["instrument"]["ticker"], "AAPL")

        div = next(a for a in payload["activities"] if a["id"] == "wealthfolio-csv-wf-csv-div-1")
        self.assertEqual(div["event_type"], "dividend")
        self.assertEqual(div["money"], {"amount": 12.4, "currency": "USD"})

        deposit = next(
            a for a in payload["activities"] if a["id"] == "wealthfolio-csv-wf-csv-dep-1"
        )
        self.assertEqual(deposit["event_type"], "transfer_in")
        self.assertEqual(deposit["money"], {"amount": 5000.0, "currency": "USD"})

        tax = next(a for a in payload["activities"] if a["id"] == "wealthfolio-csv-wf-csv-tax-1")
        self.assertEqual(tax["event_type"], "other")
        self.assertEqual(tax["subtype"], "wealthfolio:tax")
        self.assertEqual(tax["money"]["amount"], -2.1)

        draft = next(
            a for a in payload["activities"] if a["id"] == "wealthfolio-csv-wf-csv-draft-1"
        )
        self.assertEqual(draft["status"], "pending")

    def test_plugin_supports_semicolon_delimiter_and_eu_decimals(self) -> None:
        csv = (
            "id;date;symbol;activity_type;quantity;unit_price;currency;fee;account_id\n"
            "wf-csv-eu-1;2026-04-10;ASML;BUY;3;750,25;EUR;2,50;account-eu\n"
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.csv"
            path.write_text(csv, encoding="utf-8")
            payload = run_import_pipeline(
                plugin_name="wealthfolio_activity_csv",
                plugins_dir="plugins",
                input_path=str(path),
            )
        activity = payload["activities"][0]
        self.assertEqual(activity["money"], {"amount": -2250.75, "currency": "EUR"})
        self.assertEqual(activity["fees"], {"amount": 2.5, "currency": "EUR"})

    def test_plugin_rejects_missing_currency(self) -> None:
        csv = (
            "id,date,symbol,activity_type,amount\n"
            "wf-bad-1,2026-04-10,AAPL,BUY,-100\n"
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.csv"
            path.write_text(csv, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"missing currency"):
                run_import_pipeline(
                    plugin_name="wealthfolio_activity_csv",
                    plugins_dir="plugins",
                    input_path=str(path),
                )


if __name__ == "__main__":
    unittest.main()
