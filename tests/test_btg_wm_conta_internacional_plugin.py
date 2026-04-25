from __future__ import annotations

import unittest
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from plugins.btg_wm_conta_internacional import importer
from rikdom.plugin_engine.pipeline import run_import_pipeline


class BtgWmContaInternacionalPluginTests(unittest.TestCase):
    def test_plugin_parses_sample_statement_fixture(self) -> None:
        payload = run_import_pipeline(
            plugin_name="btg_wm_conta_internacional",
            plugins_dir="plugins",
            input_path="plugins/btg_wm_conta_internacional/fixtures/sample/input.txt",
        )

        self.assertEqual(payload["provider"], "btg_wm_conta_internacional")
        self.assertEqual(payload["base_currency"], "USD")
        self.assertEqual(len(payload["holdings"]), 8)
        # 12 real activities + 8 synthesized opening balances (one per holding)
        self.assertEqual(len(payload["activities"]), 20)
        opens = [a for a in payload["activities"] if a["event_type"] == "transfer_in"
                 and a.get("subtype") == "opening_balance"]
        self.assertEqual(len(opens), 8)
        for op in opens:
            self.assertTrue(op["metadata"].get("synthesized"))

        total_assets = sum(float(h["market_value"]["amount"]) for h in payload["holdings"])
        self.assertAlmostEqual(total_assets, payload["metadata"]["ending_account_value"], places=2)

        cash_holding = next(h for h in payload["holdings"] if h["identifiers"]["ticker"] == "DWBDS")
        self.assertEqual(cash_holding["asset_type_id"], "cash_equivalent")

        withholding = next(
            a
            for a in payload["activities"]
            if a["metadata"]["activity_type"] == "DIVNRA" and a["instrument"]["ticker"] == "BND"
        )
        self.assertEqual(withholding["event_type"], "fee")
        self.assertEqual(withholding["subtype"], "withholding_tax")
        self.assertEqual(withholding["money"]["amount"], -153.73)

    def test_parse_statement_pdf_uses_pdftotext_stdout(self) -> None:
        sample_txt = Path("plugins/btg_wm_conta_internacional/fixtures/sample/input.txt").read_text(
            encoding="utf-8"
        )

        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "statement.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n")

            completed = mock.Mock()
            completed.stdout = sample_txt

            with mock.patch.object(importer.subprocess, "run", return_value=completed) as run_mock:
                payload = importer.parse_statement(pdf_path)

            self.assertEqual(payload["provider"], "btg_wm_conta_internacional")
            self.assertAlmostEqual(
                payload["metadata"]["ending_account_value"],
                sum(float(h["market_value"]["amount"]) for h in payload["holdings"]),
                places=2,
            )
            run_mock.assert_called_once_with(
                ["pdftotext", "-layout", str(pdf_path), "-"],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_parse_statement_rejects_total_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            statement_path = Path(tmp) / "statement.txt"
            source = Path("plugins/btg_wm_conta_internacional/fixtures/sample/input.txt").read_text(
                encoding="utf-8"
            )
            altered = re.sub(
                r"(Ending Account Value\s+\$)1,845,914\.90",
                r"\g<1>1,845,900.00",
                source,
                count=1,
            )
            statement_path.write_text(altered, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "BTG WM statement total mismatch"):
                importer.parse_statement(statement_path)


class OpeningBalanceSynthesisTests(unittest.TestCase):
    """Targeted coverage for branches added in 948ba3a."""

    @staticmethod
    def _holding(
        *,
        ticker: str,
        asset_type_id: str,
        quantity: float,
        amount: float,
        currency: str = "USD",
    ) -> dict:
        return {
            "id": f"btgwm:acct:{ticker.lower()}",
            "asset_type_id": asset_type_id,
            "label": ticker,
            "quantity": quantity,
            "market_value": {"amount": amount, "currency": currency},
            "identifiers": {"ticker": ticker, "provider_account_id": "ACCT-1"},
            "jurisdiction": {"country": "US"},
            "metadata": {"provider": "btg-wm-conta-internacional"},
        }

    def test_unsupported_event_with_nonzero_quantity_raises(self) -> None:
        """An unmapped event_type carrying nonzero qty must raise — silently
        dropping it would leave the synthesized opening balance off by qty."""
        holdings = [
            self._holding(
                ticker="ACWI", asset_type_id="stock", quantity=10.0, amount=1000.0
            )
        ]
        activities = [
            {
                "id": "act-bad",
                "event_type": "merger",  # not in _QTY_SIGNS
                "instrument": {"ticker": "ACWI"},
                "quantity": 2.0,
                "money": {"amount": 0.0, "currency": "USD"},
            }
        ]
        with self.assertRaisesRegex(ValueError, "unsupported event_type 'merger'"):
            importer._synthesize_opening_balances(
                holdings,
                activities,
                account_number="ACCT-1",
                period_start="2026-03-01",
            )

    def test_unsupported_cash_event_does_not_raise_for_non_cash_holding(self) -> None:
        """The cash-sign guard must be conditional: tradable instruments
        don't consume the cash delta, so an unmapped cash-only event
        (e.g. exotic fee variant) for a stock holding must not fail."""
        holdings = [
            self._holding(
                ticker="VOO", asset_type_id="stock", quantity=5.0, amount=500.0
            )
        ]
        activities = [
            {
                "id": "act-cash-only",
                "event_type": "wire_charge",  # not in _CASH_SIGNS
                "instrument": {"ticker": "VOO"},
                "quantity": 0.0,
                "money": {"amount": -1.5, "currency": "USD"},
            }
        ]
        opens = importer._synthesize_opening_balances(
            holdings,
            activities,
            account_number="ACCT-1",
            period_start="2026-03-01",
        )
        self.assertEqual(len(opens), 1)
        # No cash adjustment was applied to a non-cash holding.
        self.assertEqual(opens[0]["money"]["amount"], 500.0)
        self.assertEqual(opens[0]["quantity"], 5.0)

    def test_unsupported_cash_event_raises_for_cash_holding(self) -> None:
        """For a cash_equivalent holding the cash delta IS used, so an
        unmapped event with money must still raise."""
        holdings = [
            self._holding(
                ticker="DWBDS",
                asset_type_id="cash_equivalent",
                quantity=100.0,
                amount=100.0,
            )
        ]
        activities = [
            {
                "id": "act-cash-only",
                "event_type": "wire_charge",
                "instrument": {"ticker": "DWBDS"},
                "quantity": 0.0,
                "money": {"amount": -1.5, "currency": "USD"},
            }
        ]
        with self.assertRaisesRegex(ValueError, "unsupported event_type 'wire_charge'"):
            importer._synthesize_opening_balances(
                holdings,
                activities,
                account_number="ACCT-1",
                period_start="2026-03-01",
            )

    def test_effective_at_falls_back_to_period_end_then_epoch(self) -> None:
        """Without period_start the synthetic effective_at must use
        period_end; without either it must be a deterministic epoch
        timestamp (never wall-clock now())."""
        holdings = [
            self._holding(
                ticker="ACWI", asset_type_id="stock", quantity=1.0, amount=100.0
            )
        ]

        opens_with_end = importer._synthesize_opening_balances(
            holdings,
            [],
            account_number="ACCT-1",
            period_start=None,
            period_end="2026-03-31",
        )
        self.assertEqual(opens_with_end[0]["effective_at"], "2026-03-31T00:00:00Z")

        opens_no_dates = importer._synthesize_opening_balances(
            holdings,
            [],
            account_number="ACCT-1",
            period_start=None,
            period_end=None,
        )
        self.assertEqual(opens_no_dates[0]["effective_at"], "1970-01-01T00:00:00Z")

    def test_synthetic_opening_amount_is_rounded_to_cents(self) -> None:
        """Opening money must be rounded to 2 decimals so cash drift
        comparisons aren't polluted by float noise."""
        holdings = [
            self._holding(
                ticker="DWBDS",
                asset_type_id="cash_equivalent",
                quantity=2742.28,
                amount=2742.28,
            )
        ]
        # Cash delta of 2016.5400000000003 (float noise) -> opening
        # would be 725.7399999999998 without rounding.
        activities = [
            {
                "id": "act-1",
                "event_type": "transfer_in",
                "instrument": {"ticker": "DWBDS"},
                "quantity": 1000.5400000000003,
                "money": {"amount": 1000.5400000000003, "currency": "USD"},
            },
            {
                "id": "act-2",
                "event_type": "transfer_in",
                "instrument": {"ticker": "DWBDS"},
                "quantity": 1016.0,
                "money": {"amount": 1016.0, "currency": "USD"},
            },
        ]
        opens = importer._synthesize_opening_balances(
            holdings,
            activities,
            account_number="ACCT-1",
            period_start="2026-03-01",
        )
        self.assertEqual(opens[0]["money"]["amount"], 725.74)
        # Quantity intentionally not rounded; only the persisted ledger
        # money amount is rounded to cents.


if __name__ == "__main__":
    unittest.main()
