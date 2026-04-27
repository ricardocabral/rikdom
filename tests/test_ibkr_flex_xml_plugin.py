from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from plugins.ibkr_flex_xml import importer as ibkr_importer
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

    def test_load_xml_rejects_oversized_input(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.xml"
            path.write_text("<FlexQueryResponse/>", encoding="utf-8")
            with mock.patch.object(ibkr_importer, "MAX_XML_BYTES", 4):
                with self.assertRaisesRegex(ValueError, r"exceeds .* bytes"):
                    ibkr_importer._load_xml(path)

    def test_load_xml_rejects_forbidden_dtd(self) -> None:
        with self.assertRaisesRegex(ValueError, r"Unsafe IBKR Flex XML rejected"):
            run_import_pipeline(
                plugin_name="ibkr_flex_xml",
                plugins_dir="plugins",
                input_path="tests/fixtures/ibkr_flex_statement_with_dtd.xml",
            )

    def test_unknown_trade_type_without_proceeds_fails(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements count="1">
    <FlexStatement accountId="U1" whenGenerated="20260421;150000">
      <Trades>
        <Trade transactionID="tx-unknown-1" symbol="XYZ" buySell="EXERCISE"
               quantity="3" tradePrice="50.00" currency="USD"
               dateTime="20260420;120000"/>
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown.xml"
            path.write_text(xml, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"event_type='other'.*cannot infer cashflow sign"):
                ibkr_importer.parse_statement(path)

    def test_plugin_filters_cancellations_and_maps_corporate_actions(self) -> None:
        payload = run_import_pipeline(
            plugin_name="ibkr_flex_xml",
            plugins_dir="plugins",
            input_path="tests/fixtures/ibkr_flex_statement_corporate_actions.xml",
        )

        ids = {a["id"] for a in payload["activities"]}
        self.assertNotIn("ibkr-trade-tx-cancel-flag-1", ids)
        self.assertNotIn("ibkr-trade-tx-cancel-code-1", ids)
        self.assertNotIn("ibkr-ca-ca-cancelled-1", ids)
        self.assertIn("ibkr-trade-tx-buy-real", ids)

        split = next(a for a in payload["activities"] if a["id"] == "ibkr-ca-ca-split-1")
        self.assertEqual(split["event_type"], "split")
        self.assertEqual(split["quantity"], 9.0)
        self.assertEqual(split["instrument"]["ticker"], "AAPL")
        self.assertEqual(split["metadata"]["corporate_action_type"], "FS")
        self.assertNotIn("money", split)

        merger = next(a for a in payload["activities"] if a["id"] == "ibkr-ca-ca-merger-1")
        self.assertEqual(merger["event_type"], "other")
        self.assertEqual(merger["subtype"], "ibkr_corporate_action:tc")
        self.assertEqual(merger["money"], {"amount": 2500.0, "currency": "USD"})
        self.assertEqual(merger["quantity"], 50.0)
        self.assertEqual(merger["instrument"]["ticker"], "XYZ")

    def test_plugin_idempotent_for_repeated_cancellations(self) -> None:
        payload = run_import_pipeline(
            plugin_name="ibkr_flex_xml",
            plugins_dir="plugins",
            input_path="tests/fixtures/ibkr_flex_statement_corporate_actions.xml",
        )
        ids = [a["id"] for a in payload["activities"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("ibkr-trade-tx-cancel-flag-1", ids)

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
