from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.cli import main


PORTFOLIO = {
    "schema_version": "1.5.0",
    "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
    "profile": {"portfolio_id": "test", "owner_kind": "person", "display_name": "Test"},
    "settings": {"base_currency": "BRL"},
    "asset_type_catalog": [{"id": "reit", "label": "FII", "asset_class": "reits"}],
    "holdings": [
        {
            "id": "fii",
            "asset_type_id": "reit",
            "label": "Test FII",
            "identifiers": {"ticker": "TEST11"},
            "quantity": 10,
            "market_value": {"amount": 1100, "currency": "BRL"},
            "as_of": "2026-01-01T00:00:00Z",
            "extensions": {
                "rikdom_instrument_history": {
                    "status": "complete", "from": "2025-01-01", "through": "2026-01-01"
                }
            },
        }
    ],
    "activities": [
        {
            "id": "buy", "event_type": "buy", "status": "posted",
            "effective_at": "2025-01-01T00:00:00Z", "holding_id": "fii",
            "quantity": 10, "money": {"amount": 1000, "currency": "BRL"},
        },
        {
            "id": "div", "event_type": "dividend", "status": "posted",
            "effective_at": "2026-01-01T00:00:00Z", "holding_id": "fii",
            "money": {"amount": 50, "currency": "BRL"},
        },
    ],
}


class InstrumentPerformanceCliTests(unittest.TestCase):
    def run_cli(self, portfolio: dict, *extra: str) -> tuple[int, dict | None, str]:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(json.dumps(portfolio), encoding="utf-8")
            before = path.read_bytes()
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    code = main(["performance", "--portfolio", str(path), *extra])
                except SystemExit as exc:
                    code = int(exc.code)
            self.assertEqual(path.read_bytes(), before)
            payload = json.loads(out.getvalue()) if out.getvalue().strip() else None
            return code, payload, err.getvalue()

    def test_instrument_return_needs_no_portfolio_snapshots(self) -> None:
        code, payload, err = self.run_cli(PORTFOLIO, "--by", "instrument", "--instrument", "TEST11")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(payload["by_instrument"]), 1)
        result = payload["by_instrument"][0]
        self.assertEqual(result["holding_id"], "fii")
        self.assertAlmostEqual(result["xirr_pct"], 15, places=5)
        self.assertEqual(result["profit_amount"], 150)

    def test_partial_history_never_reports_since_purchase_return(self) -> None:
        portfolio = copy.deepcopy(PORTFOLIO)
        portfolio["holdings"][0]["extensions"]["rikdom_instrument_history"]["status"] = "partial"
        code, payload, err = self.run_cli(portfolio, "--by", "instrument")
        self.assertEqual(code, 0, err)
        result = payload["by_instrument"][0]
        self.assertEqual(result["status"], "incomplete_history")
        self.assertIsNone(result["xirr_pct"])
        self.assertIsNone(result["profit_amount"])
        self.assertEqual(result["observed_distributions"], 50)

    def test_terminal_value_requires_one_selected_instrument(self) -> None:
        code, _, err = self.run_cli(PORTFOLIO, "--by", "instrument", "--terminal-value", "1200")
        self.assertEqual(code, 1)
        self.assertIn("--instrument", err)

    def test_hypothetical_terminal_value_uses_explicit_date(self) -> None:
        code, payload, err = self.run_cli(
            PORTFOLIO, "--by", "instrument", "--instrument", "fii",
            "--until", "2026-01-01", "--terminal-value", "1200",
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(payload["by_instrument"][0]["terminal_value"], 1200)
        self.assertAlmostEqual(payload["by_instrument"][0]["xirr_pct"], 25, places=4)

    def test_unknown_ticker_returns_an_actionable_error(self) -> None:
        code, _, err = self.run_cli(PORTFOLIO, "--by", "instrument", "--instrument", "UNKNOWN11")
        self.assertEqual(code, 1)
        self.assertIn("UNKNOWN11", err)

    def test_ambiguous_active_ticker_requires_holding_id(self) -> None:
        portfolio = copy.deepcopy(PORTFOLIO)
        second = copy.deepcopy(portfolio["holdings"][0])
        second["id"] = "another-account"
        portfolio["holdings"].append(second)
        code, _, err = self.run_cli(portfolio, "--by", "instrument", "--instrument", "TEST11")
        self.assertEqual(code, 1)
        self.assertIn("holding", err.lower())

    def test_since_window_is_rejected_without_an_opening_instrument_value(self) -> None:
        code, _, err = self.run_cli(PORTFOLIO, "--by", "instrument", "--since", "2025-07-01")
        self.assertEqual(code, 1)
        self.assertIn("--since", err)

    def test_instrument_options_are_rejected_in_portfolio_mode(self) -> None:
        code, _, err = self.run_cli(PORTFOLIO, "--instrument", "TEST11")
        self.assertEqual(code, 1)
        self.assertIn("--by instrument", err)


if __name__ == "__main__":
    unittest.main()
