from __future__ import annotations

import unittest

from rikdom.plugin_engine.pipeline import run_import_pipeline


class IbkrFlexXmlPluginTests(unittest.TestCase):
    def test_plugin_maps_trades_and_cash_transactions(self) -> None:
        payload = run_import_pipeline(
            plugin_name="ibkr_flex_xml",
            plugins_dir="plugins",
            input_path="tests/fixtures/ibkr_flex_statement_sample.xml",
        )

        self.assertEqual(payload["provider"], "ibkr_flex_xml")
        self.assertEqual(payload["generated_at"], "2026-04-21T14:30:00Z")
        self.assertNotIn("holdings", payload)
        self.assertEqual(len(payload["activities"]), 6)

        buy = next(a for a in payload["activities"] if a["id"] == "ibkr-trade-tx-buy-1")
        self.assertEqual(buy["event_type"], "buy")
        self.assertEqual(buy["effective_at"], "2026-04-20T14:30:15Z")
        self.assertEqual(buy["money"], {"amount": -1702.5, "currency": "USD"})
        self.assertEqual(buy["fees"], {"amount": 1.25, "currency": "USD"})
        self.assertEqual(buy["quantity"], 10.0)
        self.assertEqual(buy["instrument"]["ticker"], "AAPL")
        self.assertEqual(buy["source_ref"], "ibkr:U1234567#trade:tx-buy-1")

        sell = next(a for a in payload["activities"] if a["id"] == "ibkr-trade-tx-sell-1")
        self.assertEqual(sell["event_type"], "sell")
        self.assertEqual(sell["money"], {"amount": 2000.0, "currency": "USD"})

        dividend = next(a for a in payload["activities"] if a["id"] == "ibkr-cash-cash-div-1")
        self.assertEqual(dividend["event_type"], "dividend")
        self.assertEqual(dividend["money"], {"amount": 12.34, "currency": "USD"})
        self.assertEqual(dividend["instrument"]["ticker"], "AAPL")

        transfer_in = next(a for a in payload["activities"] if a["id"] == "ibkr-cash-cash-dep-1")
        self.assertEqual(transfer_in["event_type"], "transfer_in")

        fee = next(a for a in payload["activities"] if a["id"] == "ibkr-cash-cash-fee-1")
        self.assertEqual(fee["event_type"], "fee")

        ids = {a["id"] for a in payload["activities"]}
        self.assertNotIn("ibkr-trade-tx-cancel-1", ids)

    def test_plugin_falls_back_to_other_for_unknown_classifications(self) -> None:
        payload = run_import_pipeline(
            plugin_name="ibkr_flex_xml",
            plugins_dir="plugins",
            input_path="tests/fixtures/ibkr_flex_statement_unknown_types.xml",
        )

        trade = next(a for a in payload["activities"] if a["id"] == "ibkr-trade-tx-exotic-1")
        self.assertEqual(trade["event_type"], "other")
        self.assertEqual(trade["subtype"], "ibkr_trade:exercise")
        self.assertEqual(trade["metadata"]["buy_sell"], "EXERCISE")

        cash = next(a for a in payload["activities"] if a["id"] == "ibkr-cash-cash-adj-1")
        self.assertEqual(cash["event_type"], "other")
        self.assertTrue(cash["subtype"].startswith("ibkr_cash:adjustment"))
        self.assertEqual(cash["metadata"]["cash_type"], "Adjustment")

    def test_plugin_raises_for_unparseable_trade_date(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"IBKR trade row 'tx-bad-date' has unparseable date/time fields",
        ):
            run_import_pipeline(
                plugin_name="ibkr_flex_xml",
                plugins_dir="plugins",
                input_path="tests/fixtures/ibkr_flex_statement_bad_date.xml",
            )


if __name__ == "__main__":
    unittest.main()
