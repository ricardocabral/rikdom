from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.plugin_engine.pipeline import run_import_pipeline


class WealthfolioExportJsonPluginTests(unittest.TestCase):
    def test_plugin_maps_activities_and_holdings(self) -> None:
        payload = run_import_pipeline(
            plugin_name="wealthfolio_export_json",
            plugins_dir="plugins",
            input_path="tests/fixtures/wealthfolio_export_sample.json",
        )

        self.assertEqual(payload["provider"], "wealthfolio_export_json")
        self.assertEqual(payload["generated_at"], "2026-04-21T08:00:00Z")
        self.assertEqual(len(payload["activities"]), 5)
        self.assertEqual(len(payload["holdings"]), 1)

        buy = next(a for a in payload["activities"] if a["id"] == "wealthfolio-wf-act-buy-1")
        self.assertEqual(buy["event_type"], "buy")
        self.assertEqual(buy["effective_at"], "2026-03-01T15:30:00Z")
        self.assertEqual(buy["money"], {"amount": -1702.5, "currency": "USD"})
        self.assertEqual(buy["fees"], {"amount": 1.5, "currency": "USD"})
        self.assertEqual(buy["quantity"], 10.0)
        self.assertEqual(buy["instrument"]["ticker"], "AAPL")
        self.assertEqual(buy["instrument"]["isin"], "US0378331005")

        div = next(a for a in payload["activities"] if a["id"] == "wealthfolio-wf-act-div-1")
        self.assertEqual(div["event_type"], "dividend")
        self.assertEqual(div["money"], {"amount": 12.4, "currency": "USD"})

        deposit = next(
            a for a in payload["activities"] if a["id"] == "wealthfolio-wf-act-deposit-1"
        )
        self.assertEqual(deposit["event_type"], "transfer_in")
        self.assertEqual(deposit["money"], {"amount": 5000.0, "currency": "USD"})

        tax = next(a for a in payload["activities"] if a["id"] == "wealthfolio-wf-act-tax-1")
        self.assertEqual(tax["event_type"], "other")
        self.assertEqual(tax["subtype"], "wealthfolio:tax")
        self.assertEqual(tax["money"], {"amount": -2.1, "currency": "USD"})

        draft = next(a for a in payload["activities"] if a["id"] == "wealthfolio-wf-act-draft-1")
        self.assertEqual(draft["status"], "pending")
        self.assertEqual(draft["money"]["currency"], "USD")

        holding = payload["holdings"][0]
        self.assertEqual(holding["id"], "wealthfolio-wf-hold-aapl")
        self.assertEqual(holding["asset_type_id"], "stock")
        self.assertEqual(holding["market_value"], {"amount": 1750.0, "currency": "USD"})
        self.assertEqual(holding["identifiers"]["ticker"], "AAPL")
        self.assertEqual(holding["provenance"]["source_ref"], "account-main")

    def test_plugin_falls_back_to_other_for_unknown_activity_type(self) -> None:
        payload_data = {
            "activities": [
                {
                    "id": "wf-act-unknown-1",
                    "account_id": "account-main",
                    "activity_type": "MYSTERY",
                    "activity_date": "2026-03-01",
                    "amount": 100,
                    "currency": "USD",
                }
            ]
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.json"
            path.write_text(json.dumps(payload_data), encoding="utf-8")
            payload = run_import_pipeline(
                plugin_name="wealthfolio_export_json",
                plugins_dir="plugins",
                input_path=str(path),
            )
        unknown = payload["activities"][0]
        self.assertEqual(unknown["event_type"], "other")
        self.assertEqual(unknown["subtype"], "wealthfolio:mystery")

    def test_plugin_uses_asset_currency_when_activity_currency_missing(self) -> None:
        payload_data = {
            "assets": [
                {"id": "asset-eur-bond", "symbol": "BUND10", "asset_type": "bond", "currency": "EUR"}
            ],
            "activities": [
                {
                    "id": "wf-act-fallback-1",
                    "account_id": "account-eu",
                    "asset_id": "asset-eur-bond",
                    "activity_type": "BUY",
                    "activity_date": "2026-04-01",
                    "quantity": 5,
                    "unit_price": 100,
                }
            ],
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.json"
            path.write_text(json.dumps(payload_data), encoding="utf-8")
            payload = run_import_pipeline(
                plugin_name="wealthfolio_export_json",
                plugins_dir="plugins",
                input_path=str(path),
            )
        activity = payload["activities"][0]
        self.assertEqual(activity["money"], {"amount": -500.0, "currency": "EUR"})
        self.assertEqual(activity["instrument"]["ticker"], "BUND10")

    def test_plugin_rejects_activity_without_currency(self) -> None:
        payload_data = {
            "activities": [
                {
                    "id": "wf-act-bad-1",
                    "account_id": "account-main",
                    "activity_type": "BUY",
                    "activity_date": "2026-04-01",
                    "quantity": 5,
                    "unit_price": 100,
                }
            ]
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "wf.json"
            path.write_text(json.dumps(payload_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"no resolvable currency"):
                run_import_pipeline(
                    plugin_name="wealthfolio_export_json",
                    plugins_dir="plugins",
                    input_path=str(path),
                )


if __name__ == "__main__":
    unittest.main()
