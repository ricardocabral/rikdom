from __future__ import annotations

import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from rikdom.performance import (
    Cashflow,
    PerformanceResult,
    compute_performance,
    compute_performance_by_account,
    compute_performance_by_strategic_bucket,
    external_cashflow_currencies,
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

    def test_outflows_use_absolute_money_before_sign(self) -> None:
        activities = [
            {
                "id": "a-withdraw-negative",
                "event_type": "withdrawal",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": -300, "currency": "BRL"},
            },
            {
                "id": "a-transfer-negative",
                "event_type": "transfer_out",
                "status": "posted",
                "effective_at": "2026-02-02T00:00:00Z",
                "money": {"amount": -200, "currency": "BRL"},
            },
        ]
        flows, warnings = extract_external_cashflows(activities, "BRL")
        self.assertEqual(warnings, [])
        self.assertEqual([flow.amount_base for flow in flows], [-300.0, -200.0])

    def test_external_cashflow_currencies_ignores_internal_and_base_events(
        self,
    ) -> None:
        activities = [
            {
                "event_type": "buy",
                "status": "posted",
                "money": {"amount": 100, "currency": "EUR"},
            },
            {
                "event_type": "contribution",
                "status": "posted",
                "money": {"amount": 100, "currency": "usd"},
            },
            {
                "event_type": "transfer_out",
                "status": "posted",
                "money": {"amount": 100, "currency": "BRL"},
            },
        ]
        self.assertEqual(external_cashflow_currencies(activities, "BRL"), ["USD"])

    def test_external_cashflow_currencies_uses_period_bounds(self) -> None:
        activities = [
            {
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2025-12-31T00:00:00Z",
                "money": {"amount": 100, "currency": "EUR"},
            },
            {
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": 100, "currency": "USD"},
            },
        ]
        self.assertEqual(
            external_cashflow_currencies(
                activities,
                "BRL",
                period_start=_dt("2026-01-01T00:00:00Z"),
                period_end=_dt("2026-12-31T00:00:00Z"),
            ),
            ["USD"],
        )

    def test_external_cashflow_currencies_ignores_metadata_fx_fallbacks(
        self,
    ) -> None:
        activities = [
            {
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": 100, "currency": "EUR"},
                "metadata": {"fx_rate_to_base": 5.0},
            },
            {
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-02-01T00:00:00Z",
                "money": {"amount": 100, "currency": "USD"},
            },
        ]
        self.assertEqual(external_cashflow_currencies(activities, "BRL"), ["USD"])


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
        assert result.twr_pct is not None
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
        assert result.twr_pct is not None
        self.assertAlmostEqual(result.twr_pct, 10.0, places=4)
        self.assertEqual(result.start_value_base, 100_000.0)

    def test_date_only_until_includes_entire_calendar_day(self) -> None:
        snapshots = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 100_000, "by_asset_class": {}},
            },
            {
                "timestamp": "2026-12-31T18:00:00Z",
                "base_currency": "BRL",
                "totals": {"portfolio_value_base": 110_000, "by_asset_class": {}},
            },
        ]
        activities = [
            {
                "id": "same-day-withdrawal",
                "event_type": "withdrawal",
                "status": "posted",
                "effective_at": "2026-12-31T12:00:00Z",
                "money": {"amount": 1_000, "currency": "BRL"},
            }
        ]
        result = compute_performance(
            snapshots, activities, base_currency="BRL", until="2026-12-31"
        )
        self.assertEqual(result.end_value_base, 110_000.0)
        self.assertEqual(result.cashflow_count, 1)
        self.assertAlmostEqual(result.net_external_cashflow_base, -1_000.0)


class ComputePerformanceByAccountTests(unittest.TestCase):
    SNAPS_WITH_BY_ACCOUNT = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "base_currency": "BRL",
            "totals": {
                "portfolio_value_base": 100_000,
                "by_asset_class": {},
                "by_account": {"acc-a": 70_000.0, "acc-b": 30_000.0},
            },
        },
        {
            "timestamp": "2026-12-31T00:00:00Z",
            "base_currency": "BRL",
            "totals": {
                "portfolio_value_base": 121_000,
                "by_asset_class": {},
                "by_account": {"acc-a": 80_000.0, "acc-b": 41_000.0},
            },
        },
    ]

    def test_per_account_totals_match_brute_force(self) -> None:
        results, warnings = compute_performance_by_account(
            self.SNAPS_WITH_BY_ACCOUNT, [], base_currency="BRL"
        )
        by_id = {r.account_id: r for r in results}
        self.assertEqual(set(by_id), {"acc-a", "acc-b"})
        self.assertEqual(by_id["acc-a"].start_value_base, 70_000.0)
        self.assertEqual(by_id["acc-a"].end_value_base, 80_000.0)
        # No external flows -> TWR is the simple ratio.
        assert by_id["acc-a"].twr_pct is not None
        self.assertAlmostEqual(by_id["acc-a"].twr_pct, 100.0 * (80_000 / 70_000 - 1), places=4)
        self.assertEqual(warnings, [])

    def test_cashflow_attributed_to_named_account(self) -> None:
        activities = [
            {
                "id": "contrib-a",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-06-01T00:00:00Z",
                "account_id": "acc-a",
                "money": {"amount": 5_000.0, "currency": "BRL"},
            }
        ]
        results, warnings = compute_performance_by_account(
            self.SNAPS_WITH_BY_ACCOUNT, activities, base_currency="BRL"
        )
        by_id = {r.account_id: r for r in results}
        self.assertEqual(by_id["acc-a"].cashflow_count, 1)
        self.assertEqual(by_id["acc-a"].net_external_cashflow_base, 5_000.0)
        self.assertEqual(by_id["acc-b"].cashflow_count, 0)
        # No top-level warnings (every activity has an account_id).
        self.assertNotIn(
            "attributed to '__unassigned__'", " ".join(warnings)
        )

    def test_unattributed_activity_goes_to_unassigned_with_warning(self) -> None:
        activities = [
            {
                "id": "contrib-x",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-06-01T00:00:00Z",
                "money": {"amount": 1_000.0, "currency": "BRL"},
            }
        ]
        results, warnings = compute_performance_by_account(
            self.SNAPS_WITH_BY_ACCOUNT, activities, base_currency="BRL"
        )
        ids = {r.account_id for r in results}
        self.assertIn("__unassigned__", ids)
        self.assertTrue(
            any("__unassigned__" in w for w in warnings),
            f"expected unassigned warning, got: {warnings}",
        )

    def test_missing_by_account_in_snapshot_emits_warning(self) -> None:
        snapshots_no_by_account = [
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
        results, warnings = compute_performance_by_account(
            snapshots_no_by_account, [], base_currency="BRL"
        )
        self.assertEqual(results, [])
        self.assertTrue(any("by_account" in w for w in warnings))

    def test_account_only_in_end_snapshot_treats_start_as_zero(self) -> None:
        snapshots = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "base_currency": "BRL",
                "totals": {
                    "portfolio_value_base": 100_000,
                    "by_asset_class": {},
                    "by_account": {"acc-a": 100_000.0},
                },
            },
            {
                "timestamp": "2026-12-31T00:00:00Z",
                "base_currency": "BRL",
                "totals": {
                    "portfolio_value_base": 115_000,
                    "by_asset_class": {},
                    "by_account": {"acc-a": 105_000.0, "acc-new": 10_000.0},
                },
            },
        ]
        activities = [
            {
                "id": "fund-new",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-09-01T00:00:00Z",
                "account_id": "acc-new",
                "money": {"amount": 10_000.0, "currency": "BRL"},
            }
        ]
        results, _ = compute_performance_by_account(
            snapshots, activities, base_currency="BRL"
        )
        by_id = {r.account_id: r for r in results}
        new_acc = by_id["acc-new"]
        self.assertEqual(new_acc.start_value_base, 0.0)
        self.assertEqual(new_acc.end_value_base, 10_000.0)
        self.assertTrue(any("start snapshot" in w for w in new_acc.warnings))


class ComputePerformanceByStrategicBucketTests(unittest.TestCase):
    SNAPS = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "base_currency": "BRL",
            "totals": {
                "portfolio_value_base": 100_000,
                "by_asset_class": {},
                "by_strategic_bucket": {
                    "asset_class:stocks": 60_000.0,
                    "asset_class:debt": 30_000.0,
                    "__unallocated__": 10_000.0,
                },
            },
        },
        {
            "timestamp": "2026-12-31T00:00:00Z",
            "base_currency": "BRL",
            "totals": {
                "portfolio_value_base": 121_000,
                "by_asset_class": {},
                "by_strategic_bucket": {
                    "asset_class:stocks": 75_000.0,
                    "asset_class:debt": 32_000.0,
                    "__unallocated__": 14_000.0,
                },
            },
        },
    ]

    POLICY = {
        "strategic_allocation": {
            "targets": [
                {"dimension": "asset_class", "bucket": "stocks", "weight_pct": 60},
                {"dimension": "asset_class", "bucket": "debt", "weight_pct": 40},
            ]
        }
    }

    PORTFOLIO = {
        "asset_type_catalog": [
            {"id": "stock", "asset_class": "stocks"},
            {"id": "bond", "asset_class": "debt"},
            {"id": "crypto", "asset_class": "cryptocurrencies"},
        ],
        "holdings": [
            {"id": "h-stock", "asset_type_id": "stock"},
            {"id": "h-bond", "asset_type_id": "bond"},
            {"id": "h-crypto", "asset_type_id": "crypto"},
        ],
    }

    def test_per_bucket_totals_match_bookends(self) -> None:
        results, warnings = compute_performance_by_strategic_bucket(
            self.SNAPS,
            [],
            base_currency="BRL",
            portfolio=self.PORTFOLIO,
            policy=self.POLICY,
        )
        by_key = {r.bucket_key: r for r in results}
        self.assertEqual(
            set(by_key),
            {"asset_class:stocks", "asset_class:debt", "__unallocated__"},
        )
        self.assertEqual(by_key["asset_class:stocks"].start_value_base, 60_000.0)
        self.assertEqual(by_key["asset_class:stocks"].end_value_base, 75_000.0)
        assert by_key["asset_class:stocks"].twr_pct is not None
        self.assertAlmostEqual(
            by_key["asset_class:stocks"].twr_pct,
            100.0 * (75_000 / 60_000 - 1),
            places=4,
        )
        self.assertEqual(warnings, [])

    def test_buy_attributed_to_holding_bucket(self) -> None:
        activities = [
            {
                "id": "buy-stock",
                "event_type": "transfer_in",
                "status": "posted",
                "effective_at": "2026-06-01T00:00:00Z",
                "holding_id": "h-stock",
                "money": {"amount": 5_000.0, "currency": "BRL"},
            }
        ]
        results, _ = compute_performance_by_strategic_bucket(
            self.SNAPS,
            activities,
            base_currency="BRL",
            portfolio=self.PORTFOLIO,
            policy=self.POLICY,
        )
        by_key = {r.bucket_key: r for r in results}
        self.assertEqual(by_key["asset_class:stocks"].cashflow_count, 1)
        self.assertEqual(
            by_key["asset_class:stocks"].net_external_cashflow_base, 5_000.0
        )
        self.assertEqual(by_key["asset_class:debt"].cashflow_count, 0)

    def test_holding_outside_targets_falls_to_unallocated(self) -> None:
        activities = [
            {
                "id": "buy-crypto",
                "event_type": "transfer_in",
                "status": "posted",
                "effective_at": "2026-06-01T00:00:00Z",
                "holding_id": "h-crypto",
                "money": {"amount": 1_000.0, "currency": "BRL"},
            }
        ]
        results, _ = compute_performance_by_strategic_bucket(
            self.SNAPS,
            activities,
            base_currency="BRL",
            portfolio=self.PORTFOLIO,
            policy=self.POLICY,
        )
        by_key = {r.bucket_key: r for r in results}
        self.assertEqual(by_key["__unallocated__"].cashflow_count, 1)

    def test_activity_without_holding_id_warns(self) -> None:
        activities = [
            {
                "id": "external-contrib",
                "event_type": "contribution",
                "status": "posted",
                "effective_at": "2026-06-01T00:00:00Z",
                "money": {"amount": 1_000.0, "currency": "BRL"},
            }
        ]
        _, warnings = compute_performance_by_strategic_bucket(
            self.SNAPS,
            activities,
            base_currency="BRL",
            portfolio=self.PORTFOLIO,
            policy=self.POLICY,
        )
        self.assertTrue(any("__unallocated__" in w for w in warnings))

    def test_missing_by_strategic_bucket_emits_warning(self) -> None:
        snaps = [
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
        results, warnings = compute_performance_by_strategic_bucket(
            snaps,
            [],
            base_currency="BRL",
            portfolio=self.PORTFOLIO,
            policy=self.POLICY,
        )
        self.assertEqual(results, [])
        self.assertTrue(any("by_strategic_bucket" in w for w in warnings))


class CliPerformanceTests(unittest.TestCase):
    def test_cmd_performance_requests_fx_for_external_cashflows(self) -> None:
        from rikdom.cli import cmd_performance

        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [],
            "activities": [
                {
                    "id": "cashflow-eur",
                    "event_type": "contribution",
                    "status": "posted",
                    "effective_at": "2026-01-15T00:00:00Z",
                    "money": {"amount": 100, "currency": "EUR"},
                }
            ],
        }
        snapshots = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "totals": {"portfolio_value_base": 100},
            },
            {
                "timestamp": "2026-12-31T00:00:00Z",
                "totals": {"portfolio_value_base": 110},
            },
        ]
        result = PerformanceResult(
            base_currency="BRL",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z",
            start_value_base=100.0,
            end_value_base=110.0,
            net_external_cashflow_base=500.0,
            twr_pct=10.0,
            mwr_pct=10.0,
            cashflow_count=1,
        )
        args = Namespace(
            portfolio="portfolio.json",
            snapshots="snapshots.jsonl",
            fx_history="fx.jsonl",
            since=None,
            until=None,
        )

        with (
            mock.patch("rikdom.cli.load_json", return_value=portfolio),
            mock.patch("rikdom.cli.load_jsonl", return_value=snapshots),
            mock.patch(
                "rikdom.cli.ensure_snapshot_fx_lock",
                return_value=({"rates_to_base": {"EUR": 5.0}}, []),
            ) as mock_fx,
            mock.patch("rikdom.cli.compute_performance", return_value=result),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cmd_performance(args)

        self.assertEqual(code, 0)
        mock_fx.assert_called_once_with(
            portfolio,
            fx_history_path="fx.jsonl",
            snapshot_timestamp=mock.ANY,
            auto_ingest=False,
            extra_quote_currencies=["EUR"],
        )

    def test_cmd_performance_requests_fx_only_for_effective_window(self) -> None:
        from rikdom.cli import cmd_performance

        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [],
            "activities": [
                {
                    "id": "old-eur",
                    "event_type": "contribution",
                    "status": "posted",
                    "effective_at": "2025-06-01T00:00:00Z",
                    "money": {"amount": 100, "currency": "EUR"},
                },
                {
                    "id": "period-usd",
                    "event_type": "contribution",
                    "status": "posted",
                    "effective_at": "2026-06-01T00:00:00Z",
                    "money": {"amount": 100, "currency": "USD"},
                },
            ],
        }
        snapshots = [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "totals": {"portfolio_value_base": 90},
            },
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "totals": {"portfolio_value_base": 100},
            },
            {
                "timestamp": "2026-12-31T00:00:00Z",
                "totals": {"portfolio_value_base": 110},
            },
        ]
        result = PerformanceResult(
            base_currency="BRL",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z",
            start_value_base=100.0,
            end_value_base=110.0,
            net_external_cashflow_base=500.0,
            twr_pct=10.0,
            mwr_pct=10.0,
            cashflow_count=1,
        )
        args = Namespace(
            portfolio="portfolio.json",
            snapshots="snapshots.jsonl",
            fx_history="fx.jsonl",
            since="2026-01-01",
            until="2026-12-31",
        )

        with (
            mock.patch("rikdom.cli.load_json", return_value=portfolio),
            mock.patch("rikdom.cli.load_jsonl", return_value=snapshots),
            mock.patch(
                "rikdom.cli.ensure_snapshot_fx_lock",
                return_value=({"rates_to_base": {"USD": 5.0}}, []),
            ) as mock_fx,
            mock.patch("rikdom.cli.compute_performance", return_value=result),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cmd_performance(args)

        self.assertEqual(code, 0)
        self.assertEqual(mock_fx.call_args.kwargs["extra_quote_currencies"], ["USD"])

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
