from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.performance import (
    Cashflow,
    compute_performance,
    extract_external_cashflows,
    modified_dietz,
    xirr,
)


def _dt(s: str) -> datetime:
    text = s.endswith("Z") and s[:-1] + "+00:00" or s
    return datetime.fromisoformat(text).astimezone(timezone.utc)


class ModifiedDietzTests(unittest.TestCase):
    def test_no_cashflow_simple_return(self) -> None:
        # 100 -> 110 with no cashflow = +10%.
        r = modified_dietz(
            100.0, 110.0, [], _dt("2026-01-01T00:00:00Z"), _dt("2026-12-31T00:00:00Z")
        )
        assert r is not None
        self.assertAlmostEqual(r, 0.10, places=6)

    def test_textbook_modified_dietz(self) -> None:
        # Classic teaching example:
        #   BV = 100,000 on day 0, EV = 112,000 on day 90,
        #   contribution of +10,000 on day 30.
        # Weighted denom = 100,000 + ((90-30)/90)*10,000 = 106,666.6667
        # Numerator = 112,000 - 100,000 - 10,000 = 2,000
        # TWR = 2000 / 106666.6667 = 0.01875
        start = _dt("2026-01-01T00:00:00Z")
        flow = _dt("2026-01-31T00:00:00Z")
        end = _dt("2026-04-01T00:00:00Z")
        r = modified_dietz(
            100_000.0,
            112_000.0,
            [Cashflow(when=flow, amount_base=10_000.0)],
            start,
            end,
        )
        assert r is not None
        self.assertAlmostEqual(r, 0.01875, places=4)

    def test_zero_denominator_returns_none(self) -> None:
        # Withdraw the whole starting balance at t=0 and end with 0 value.
        start = _dt("2026-01-01T00:00:00Z")
        end = _dt("2026-12-31T00:00:00Z")
        r = modified_dietz(
            100.0,
            0.0,
            [Cashflow(when=start, amount_base=-100.0)],
            start,
            end,
        )
        # Denominator = 100 + 1.0 * (-100) = 0 -> undefined.
        self.assertIsNone(r)


class XirrTests(unittest.TestCase):
    def test_flat_doubling_in_one_year_is_100pct(self) -> None:
        cashflows = [
            Cashflow(when=_dt("2026-01-01T00:00:00Z"), amount_base=-100.0),
            Cashflow(when=_dt("2027-01-01T00:00:00Z"), amount_base=200.0),
        ]
        r = xirr(cashflows)
        assert r is not None
        self.assertAlmostEqual(r, 1.0, places=4)

    def test_zero_return(self) -> None:
        cashflows = [
            Cashflow(when=_dt("2026-01-01T00:00:00Z"), amount_base=-100.0),
            Cashflow(when=_dt("2027-01-01T00:00:00Z"), amount_base=100.0),
        ]
        r = xirr(cashflows)
        assert r is not None
        self.assertAlmostEqual(r, 0.0, places=6)

    def test_no_sign_change_returns_none(self) -> None:
        cashflows = [
            Cashflow(when=_dt("2026-01-01T00:00:00Z"), amount_base=-100.0),
            Cashflow(when=_dt("2027-01-01T00:00:00Z"), amount_base=-50.0),
        ]
        self.assertIsNone(xirr(cashflows))


class ExtractCashflowsTests(unittest.TestCase):
    def test_only_external_events_count(self) -> None:
        activities = [
            {
                "id": "a-buy",
                "event_type": "buy",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": 500, "currency": "BRL"},
            },
            {
                "id": "a-contrib",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": 1000, "currency": "BRL"},
            },
            {
                "id": "a-withdraw",
                "event_type": "withdrawal",
                "status": "posted",
                "effective_at": "2026-03-01T00:00:00Z",
                "money": {"amount": 300, "currency": "BRL"},
            },
        ]
        flows, warnings = extract_external_cashflows(activities, "BRL")
        self.assertEqual(len(flows), 2)
        self.assertAlmostEqual(flows[0].amount_base, 1000.0)
        self.assertAlmostEqual(flows[1].amount_base, -300.0)
        self.assertEqual(warnings, [])

    def test_foreign_currency_without_fx_warns(self) -> None:
        activities = [
            {
                "id": "a-fx",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": 100, "currency": "USD"},
            }
        ]
        flows, warnings = extract_external_cashflows(activities, "BRL")
        self.assertEqual(flows, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("USD", warnings[0])

    def test_foreign_currency_with_fx_converts(self) -> None:
        activities = [
            {
                "id": "a-fx",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": 100, "currency": "USD"},
            }
        ]
        flows, _ = extract_external_cashflows(
            activities, "BRL", fx_rates_to_base={"USD": 5.0}
        )
        self.assertEqual(len(flows), 1)
        self.assertAlmostEqual(flows[0].amount_base, 500.0)


class ComputePerformanceTests(unittest.TestCase):
    def test_end_to_end_no_cashflows(self) -> None:
        snapshots = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 100_000, "by_asset_class": {}},
            },
            {
                "timestamp": "2026-12-31T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 110_000, "by_asset_class": {}},
            },
        ]
        result = compute_performance(snapshots, [], base_currency="BRL")
        self.assertAlmostEqual(result.twr_pct, 10.0, places=4)
        assert result.mwr_pct is not None
        # XIRR annualizes by 365-day years; Jan 1 -> Dec 31 is 364 days,
        # so the annualized MWR is slightly above 10%.
        self.assertAlmostEqual(result.mwr_pct, 10.0, places=0)
        self.assertEqual(result.cashflow_count, 0)
        self.assertEqual(result.start_value_base, 100_000.0)
        self.assertEqual(result.end_value_base, 110_000.0)

    def test_end_to_end_with_contribution(self) -> None:
        snapshots = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 100_000, "by_asset_class": {}},
            },
            {
                "timestamp": "2026-04-01T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 112_000, "by_asset_class": {}},
            },
        ]
        activities = [
            {
                "id": "contrib",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-01-31T00:00:00Z",
                "money": {"amount": 10_000, "currency": "BRL"},
            }
        ]
        result = compute_performance(snapshots, activities, base_currency="BRL")
        # See textbook calculation in ModifiedDietzTests.
        assert result.twr_pct is not None
        self.assertAlmostEqual(result.twr_pct, 1.875, places=2)
        self.assertEqual(result.cashflow_count, 1)
        self.assertAlmostEqual(result.net_external_cashflow_base, 10_000.0)

    def test_window_filtering(self) -> None:
        snapshots = [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 80_000, "by_asset_class": {}},
            },
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 100_000, "by_asset_class": {}},
            },
            {
                "timestamp": "2026-12-31T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 110_000, "by_asset_class": {}},
            },
        ]
        result = compute_performance(
            snapshots, [], base_currency="BRL", since="2026-01-01"
        )
        self.assertAlmostEqual(result.twr_pct, 10.0, places=4)
        self.assertEqual(result.start_value_base, 100_000.0)


class CliPerformanceTests(unittest.TestCase):
    def test_cli_runs_against_sample(self) -> None:
        from rikdom.cli import main

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            portfolio_src = Path("data-sample/portfolio.json")
            snapshots_src = Path("data-sample/snapshots.jsonl")
            portfolio_dst = tmp_path / "portfolio.json"
            snapshots_dst = tmp_path / "snapshots.jsonl"
            portfolio_dst.write_bytes(portfolio_src.read_bytes())
            snapshots_dst.write_bytes(snapshots_src.read_bytes())
            out_path = tmp_path / "perf.json"
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(
                    [
                        "performance",
                        "--portfolio",
                        str(portfolio_dst),
                        "--snapshots",
                        str(snapshots_dst),
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["base_currency"], "BRL")
            self.assertGreater(payload["end_value_base"], 0)
            self.assertIn("twr_pct", payload)
            self.assertIn("mwr_pct", payload)
            out_path.write_text(buf.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
