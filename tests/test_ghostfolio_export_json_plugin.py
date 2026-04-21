from __future__ import annotations

import unittest

from rikdom.plugin_engine.pipeline import run_import_pipeline


class GhostfolioExportJsonPluginTests(unittest.TestCase):
    def test_plugin_maps_holdings_and_activities(self) -> None:
        payload = run_import_pipeline(
            plugin_name="ghostfolio_export_json",
            plugins_dir="plugins",
            input_path="tests/fixtures/ghostfolio_export_sample.json",
        )

        self.assertEqual(payload["provider"], "ghostfolio_export_json")
        self.assertEqual(payload["generated_at"], "2026-04-20T14:00:00Z")
        self.assertEqual(len(payload["activities"]), 2)
        self.assertEqual(len(payload["holdings"]), 1)

        buy = next(a for a in payload["activities"] if a["id"] == "gf-act-1")
        self.assertEqual(buy["event_type"], "buy")
        self.assertEqual(buy["effective_at"], "2026-03-01T00:00:00Z")
        self.assertEqual(buy["money"], {"amount": -1500.2, "currency": "USD"})
        self.assertEqual(buy["fees"], {"amount": 3.5, "currency": "USD"})
        self.assertEqual(buy["quantity"], 10.0)
        self.assertEqual(buy["instrument"]["ticker"], "AAPL")

        holding = payload["holdings"][0]
        self.assertEqual(holding["id"], "gf-hold-aapl")
        self.assertEqual(holding["asset_type_id"], "stock")
        self.assertEqual(holding["market_value"], {"amount": 1675.1, "currency": "USD"})
        self.assertEqual(holding["provenance"]["source_ref"], "broker-main")


if __name__ == "__main__":
    unittest.main()
