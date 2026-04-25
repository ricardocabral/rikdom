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


if __name__ == "__main__":
    unittest.main()
