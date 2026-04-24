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

    def test_plugin_parses_ofx_fixture(self) -> None:
        payload = run_import_pipeline(
            plugin_name="vanguard",
            plugins_dir="plugins",
            input_path="plugins/vanguard/fixtures/ofx-brokerage/input.ofx",
        )

        self.assertEqual(payload["provider"], "vanguard")
        self.assertEqual(payload["base_currency"], "USD")
        self.assertEqual(payload["metadata"]["input_format"], "ofx")
        self.assertEqual(len(payload["holdings"]), 3)
        self.assertEqual(len(payload["activities"]), 5)

        interest = next(
            a for a in payload["activities"] if a["event_type"] == "interest"
        )
        self.assertEqual(interest["money"], {"amount": 1.22, "currency": "USD"})

        buy = next(a for a in payload["activities"] if a["event_type"] == "buy")
        self.assertEqual(buy["money"]["amount"], -617.25)
        self.assertEqual(buy["instrument"]["ticker"], "VTSAX")

        # DTTRADE for the dividend is "20260320120000[-5:EST]"; the offset must
        # be applied before converting to UTC, not stripped.
        dividend = next(
            a for a in payload["activities"] if a["event_type"] == "dividend"
        )
        self.assertEqual(dividend["effective_at"], "2026-03-20T17:00:00Z")

    def test_ofx_datetime_applies_bracketed_timezone_offset(self) -> None:
        from plugins.vanguard.importer import _normalize_ofx_datetime

        self.assertEqual(
            _normalize_ofx_datetime("20260331120000.000[-5:EST]"),
            "2026-03-31T17:00:00Z",
        )
        self.assertEqual(
            _normalize_ofx_datetime("20260101000000[+2:CEST]"),
            "2025-12-31T22:00:00Z",
        )
        # No bracket -> treated as UTC (unchanged behavior)
        self.assertEqual(
            _normalize_ofx_datetime("20260305103000"),
            "2026-03-05T10:30:00Z",
        )

    def test_ofx_decoder_handles_cp1252_payload(self) -> None:
        from plugins.vanguard.importer import _decode_ofx_bytes

        header = (
            "OFXHEADER:100\r\nDATA:OFXSGML\r\nENCODING:USASCII\r\n"
            "CHARSET:1252\r\n\r\n"
        ).encode("ascii")
        # 0xA9 is "©" in cp1252 but invalid as standalone UTF-8.
        body = b"<OFX><NAME>Acme \xa9 Fund</NAME></OFX>"
        decoded = _decode_ofx_bytes(header + body)
        self.assertIn("Acme © Fund", decoded)

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

    def test_transaction_fingerprint_distinguishes_description_and_fees(self) -> None:
        from plugins.vanguard.importer import _parse_transaction

        base = {
            "account_number": "VG-1",
            "activity_type": "Buy",
            "amount": "-100.00",
            "date": "01/15/2026",
            "symbol": "VTI",
            "quantity": "1",
            "currency": "USD",
        }
        a = _parse_transaction({**base, "description": "buy A", "fees": "1.00"})
        b = _parse_transaction({**base, "description": "buy B", "fees": "2.00"})
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(a["idempotency_key"], b["idempotency_key"])

    def test_transaction_rejects_invalid_optional_decimal(self) -> None:
        from plugins.vanguard.importer import _parse_transaction

        bad_quantity = {
            "account_number": "VG-1",
            "activity_type": "Buy",
            "amount": "-100.00",
            "date": "01/15/2026",
            "symbol": "VTI",
            "quantity": "not-a-number",
        }
        with self.assertRaisesRegex(ValueError, "invalid quantity"):
            _parse_transaction(bad_quantity)

        bad_fees = {
            "account_number": "VG-1",
            "activity_type": "Buy",
            "amount": "-100.00",
            "date": "01/15/2026",
            "symbol": "VTI",
            "fees": "oops",
        }
        with self.assertRaisesRegex(ValueError, "invalid fees"):
            _parse_transaction(bad_fees)

    def test_plugin_rejects_invalid_amount_fixture(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid amount"):
            run_import_pipeline(
                plugin_name="vanguard",
                plugins_dir="plugins",
                input_path="plugins/vanguard/fixtures/invalid-amount/input.csv",
            )


if __name__ == "__main__":
    unittest.main()
