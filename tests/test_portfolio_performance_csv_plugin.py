from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.plugin_engine.pipeline import run_import_pipeline


class PortfolioPerformanceCsvPluginTests(unittest.TestCase):
    def test_plugin_parses_german_locale_export(self) -> None:
        payload = run_import_pipeline(
            plugin_name="portfolio_performance_csv",
            plugins_dir="plugins",
            input_path="tests/fixtures/portfolio_performance_export_de.csv",
        )

        self.assertEqual(payload["provider"], "portfolio_performance_csv")
        ids = {a["id"] for a in payload["activities"]}
        self.assertEqual(
            ids,
            {"pp-de-buy-1", "pp-de-div-1", "pp-Sparrate April", "pp-Steuerausgleich"},
        )

        buy = next(a for a in payload["activities"] if a["id"] == "pp-de-buy-1")
        self.assertEqual(buy["event_type"], "buy")
        self.assertEqual(buy["effective_at"], "2026-04-20T10:30:00Z")
        self.assertEqual(buy["money"], {"amount": -1512.75, "currency": "EUR"})
        self.assertEqual(buy["fees"], {"amount": 9.75, "currency": "EUR"})
        self.assertEqual(buy["quantity"], 10.0)
        self.assertEqual(buy["instrument"]["ticker"], "AAPL")
        self.assertEqual(buy["instrument"]["isin"], "US0378331005")
        self.assertEqual(buy["metadata"]["taxes"], {"amount": 3.0, "currency": "EUR"})

        div = next(a for a in payload["activities"] if a["id"] == "pp-de-div-1")
        self.assertEqual(div["event_type"], "dividend")
        self.assertEqual(div["money"], {"amount": 7.8, "currency": "EUR"})

        deposit = next(a for a in payload["activities"] if a["id"] == "pp-Sparrate April")
        self.assertEqual(deposit["event_type"], "transfer_in")
        self.assertEqual(deposit["money"], {"amount": 5000.0, "currency": "EUR"})

        tax = next(a for a in payload["activities"] if a["id"] == "pp-Steuerausgleich")
        self.assertEqual(tax["event_type"], "other")
        self.assertEqual(tax["subtype"], "pp:steuern")

    def test_plugin_parses_english_locale_export(self) -> None:
        payload = run_import_pipeline(
            plugin_name="portfolio_performance_csv",
            plugins_dir="plugins",
            input_path="tests/fixtures/portfolio_performance_export_en.csv",
        )

        ids = {a["id"] for a in payload["activities"]}
        self.assertIn("pp-en-buy-1", ids)

        buy = next(a for a in payload["activities"] if a["id"] == "pp-en-buy-1")
        self.assertEqual(buy["event_type"], "buy")
        self.assertEqual(buy["effective_at"], "2026-04-20T00:00:00Z")
        self.assertEqual(buy["money"], {"amount": -1702.5, "currency": "USD"})
        self.assertEqual(buy["fees"], {"amount": 2.5, "currency": "USD"})

        div = next(a for a in payload["activities"] if a["id"] == "pp-en-div-1")
        self.assertEqual(div["event_type"], "dividend")
        self.assertEqual(div["money"], {"amount": 12.34, "currency": "USD"})

        withdraw = next(a for a in payload["activities"] if a["id"] == "pp-en-withdraw-1")
        self.assertEqual(withdraw["event_type"], "transfer_out")
        self.assertEqual(withdraw["money"], {"amount": -500.0, "currency": "USD"})

    def test_plugin_rejects_missing_currency(self) -> None:
        csv = (
            "Date;Type;Value;Shares;Note\n"
            "20.04.2026;Kauf;-100,00;5;bad-row\n"
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(csv, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"missing transaction currency"):
                run_import_pipeline(
                    plugin_name="portfolio_performance_csv",
                    plugins_dir="plugins",
                    input_path=str(path),
                )

    def test_plugin_rejects_unparseable_date(self) -> None:
        csv = (
            "Date;Type;Value;Transaction Currency;Note\n"
            ";Kauf;-100,00;EUR;bad-date\n"
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(csv, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"missing required date column"):
                run_import_pipeline(
                    plugin_name="portfolio_performance_csv",
                    plugins_dir="plugins",
                    input_path=str(path),
                )


if __name__ == "__main__":
    unittest.main()
