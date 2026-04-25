from __future__ import annotations

import io
import json
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.backfill import backfill_cashflows, backfill_exposure
from rikdom.cli import main
from rikdom.storage import load_json


FIXTURE = Path("tests/fixtures/portfolio.json")


class BackfillExposureTests(unittest.TestCase):
    def test_synthesizes_stub_for_holding_without_exposure(self) -> None:
        portfolio = {
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-1",
                    "asset_type_id": "stock",
                    "label": "x",
                    "market_value": {"amount": 1.0, "currency": "USD"},
                }
            ],
        }
        new, report = backfill_exposure(portfolio, today=date(2026, 4, 25))
        self.assertEqual(report.touched, ["h-1"])
        stub = new["holdings"][0]["economic_exposure"]
        self.assertEqual(stub["classification_source"], "heuristic")
        self.assertEqual(stub["confidence"], "low")
        self.assertEqual(stub["as_of"], "2026-04-25")
        self.assertEqual(stub["breakdown"][0]["asset_class"], "stocks")
        self.assertEqual(stub["breakdown"][0]["weight_pct"], 100)

    def test_skips_when_holding_already_has_exposure(self) -> None:
        portfolio = {
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-1",
                    "asset_type_id": "stock",
                    "label": "x",
                    "market_value": {"amount": 1.0, "currency": "USD"},
                    "economic_exposure": {
                        "breakdown": [{"weight_pct": 100, "asset_class": "stocks"}]
                    },
                }
            ],
        }
        _, report = backfill_exposure(portfolio)
        self.assertEqual(report.touched, [])
        self.assertTrue(any("already has" in m for m in report.skipped))

    def test_skips_when_catalog_already_carries_exposure(self) -> None:
        portfolio = {
            "asset_type_catalog": [
                {
                    "id": "stock",
                    "asset_class": "stocks",
                    "economic_exposure": {
                        "breakdown": [{"weight_pct": 100, "asset_class": "stocks"}]
                    },
                }
            ],
            "holdings": [
                {
                    "id": "h-1",
                    "asset_type_id": "stock",
                    "label": "x",
                    "market_value": {"amount": 1.0, "currency": "USD"},
                }
            ],
        }
        _, report = backfill_exposure(portfolio)
        self.assertEqual(report.touched, [])
        self.assertTrue(any("catalog economic_exposure" in m for m in report.skipped))

        # include_catalog overrides
        new, report = backfill_exposure(portfolio, include_catalog=True)
        self.assertEqual(report.touched, ["h-1"])
        self.assertIn("economic_exposure", new["holdings"][0])

    def test_round_trip_validates(self) -> None:
        from rikdom.validate import validate_portfolio

        portfolio = load_json(FIXTURE)
        new, _ = backfill_exposure(portfolio)
        self.assertEqual(validate_portfolio(new), [])


class BackfillCashflowsTests(unittest.TestCase):
    def _portfolio(self) -> dict:
        return {
            "asset_type_catalog": [
                {"id": "td_ipca", "asset_class": "debt"}
            ],
            "holdings": [
                {
                    "id": "td-1",
                    "asset_type_id": "td_ipca",
                    "label": "Tesouro IPCA+ 2030",
                    "market_value": {"amount": 10000.0, "currency": "BRL"},
                    "fixed_income_profile": {
                        "maturity_date": "2027-06-15",
                        "coupon": {
                            "coupon_type": "FIXED",
                            "payment_frequency": "SEMIANNUAL",
                            "fixed_rate_pct": 6.0,
                            "accrual_start_date": "2025-06-15",
                        },
                    },
                }
            ],
        }

    def test_generates_interest_legs_and_principal(self) -> None:
        new, report = backfill_cashflows(self._portfolio())
        self.assertEqual(report.touched, ["td-1"])
        legs = new["holdings"][0]["fixed_income_profile"]["cash_flows"]
        kinds = [leg["kind"] for leg in legs]
        self.assertEqual(kinds.count("PRINCIPAL"), 1)
        self.assertEqual(kinds.count("INTEREST"), 4)  # 2025-12, 2026-06, 2026-12, 2027-06
        principal = next(leg for leg in legs if leg["kind"] == "PRINCIPAL")
        self.assertEqual(principal["date"], "2027-06-15")
        self.assertAlmostEqual(principal["amount"]["amount"], 10000.0)
        for leg in legs:
            self.assertEqual(leg["status"], "PROJECTED")

    def test_skips_existing_cashflows_unless_force(self) -> None:
        portfolio = self._portfolio()
        portfolio["holdings"][0]["fixed_income_profile"]["cash_flows"] = [
            {"date": "2026-01-01", "kind": "INTEREST", "amount": {"amount": 1, "currency": "BRL"}}
        ]
        _, report = backfill_cashflows(portfolio)
        self.assertEqual(report.touched, [])
        self.assertTrue(any("already present" in m for m in report.skipped))

        new, report = backfill_cashflows(portfolio, force=True)
        self.assertEqual(report.touched, ["td-1"])
        legs = new["holdings"][0]["fixed_income_profile"]["cash_flows"]
        self.assertGreater(len(legs), 1)

    def test_skips_non_fixed_coupons(self) -> None:
        portfolio = self._portfolio()
        portfolio["holdings"][0]["fixed_income_profile"]["coupon"]["coupon_type"] = "FLOATING"
        _, report = backfill_cashflows(portfolio)
        self.assertEqual(report.touched, [])


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class BackfillCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _stage(self) -> Path:
        target = self.tmp / "portfolio.json"
        shutil.copy2(FIXTURE, target)
        return target

    def test_dry_run_does_not_write(self) -> None:
        path = self._stage()
        before = path.read_bytes()
        code, stdout, _ = _run(
            ["backfill", "exposure", "--portfolio", str(path), "--dry-run"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "planned")
        self.assertEqual(path.read_bytes(), before)

    def test_writes_with_backup_by_default(self) -> None:
        path = self._stage()
        original = path.read_bytes()
        code, stdout, _ = _run(["backfill", "exposure", "--portfolio", str(path)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertIn(payload["status"], {"written", "noop"})
        if payload["status"] == "written":
            backups = list(self.tmp.glob("portfolio.json.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
