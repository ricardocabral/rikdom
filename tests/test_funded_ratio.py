from __future__ import annotations

import contextlib
import io
import json
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from rikdom.funded_ratio import compute_funded_ratios


class FundedRatioTests(unittest.TestCase):
    def test_retirement_target_projects_current_value_and_contributions(self) -> None:
        policy = {
            "identity": {"policy_base_currency": "BRL"},
            "investor_profile": {},
            "objectives": [
                {
                    "id": "retirement",
                    "label": "Retirement",
                    "kind": "retirement",
                    "priority": "must_have",
                    "target_date": "2036-01-01",
                    "funding_account_ids": ["taxable"],
                }
            ],
            "retirement_assumptions": {
                "desired_annual_spending": {"amount": 40_000, "currency": "BRL"},
                "withdrawal_rule": {"method": "fixed_pct_swr", "initial_rate_pct": 4.0},
                "target_real_return_pct": 5.0,
            },
            "cashflow_policy": {
                "contributions": [
                    {
                        "amount": {"amount": 1_000, "currency": "BRL"},
                        "cadence": {"frequency": "monthly"},
                        "account_id": "taxable",
                    },
                    {
                        "amount": {"amount": 999, "currency": "BRL"},
                        "cadence": {"frequency": "monthly"},
                        "account_id": "other",
                    },
                ]
            },
        }

        summary = compute_funded_ratios(
            500_000,
            policy,
            by_account={"taxable": 100_000, "other": 400_000},
            base_currency="BRL",
            as_of="2026-01-01",
        )

        self.assertEqual(summary.warnings, [])
        result = summary.results[0]
        self.assertEqual(result.current_value_base, 100_000)
        self.assertEqual(result.net_annual_contribution_base, 12_000)
        self.assertEqual(result.target_amount_today_base, 1_000_000)
        years = 3652 / 365.25
        growth = 1.05**years
        expected_projected = 100_000 * growth + 12_000 * ((growth - 1) / 0.05)
        self.assertAlmostEqual(
            result.projected_value_base, expected_projected, places=2
        )
        self.assertAlmostEqual(
            result.ratio or 0.0, expected_projected / 1_000_000, places=6
        )

    def test_target_amount_uses_fx_rate_and_zero_horizon(self) -> None:
        policy = {
            "identity": {"policy_base_currency": "BRL"},
            "objectives": [
                {
                    "id": "education",
                    "label": "Education",
                    "kind": "education",
                    "priority": "important",
                    "target_amount": {"amount": 10_000, "currency": "USD"},
                    "target_date": "2026-01-01",
                }
            ],
        }

        summary = compute_funded_ratios(
            30_000,
            policy,
            base_currency="BRL",
            fx_rates_to_base={"USD": 5.0},
            as_of="2026-01-01",
        )

        result = summary.results[0]
        self.assertEqual(result.target_amount_today_base, 50_000)
        self.assertEqual(result.projected_value_base, 30_000)
        self.assertEqual(result.shortfall_base, 20_000)
        self.assertTrue(any("using 0% real return" in w for w in summary.warnings))

    def test_retirement_assumptions_at_retirement_spending_is_deflated(self) -> None:
        policy = {
            "identity": {"policy_base_currency": "BRL"},
            "objectives": [
                {
                    "id": "retirement",
                    "kind": "retirement",
                    "priority": "must_have",
                    "target_date": "2036-01-01",
                }
            ],
            "retirement_assumptions": {
                "desired_annual_spending": {"amount": 121_000, "currency": "BRL"},
                "spending_basis": "at_retirement",
                "inflation_assumption_pct": 2.0,
                "withdrawal_rule": {"method": "fixed_pct_swr", "initial_rate_pct": 4.0},
                "target_real_return_pct": 0.0,
            },
        }

        summary = compute_funded_ratios(
            0, policy, base_currency="BRL", as_of="2026-01-01"
        )

        years = 3652 / 365.25
        expected_today = 121_000 / (1.02**years) / 0.04
        self.assertAlmostEqual(
            summary.results[0].target_amount_today_base or 0.0,
            round(expected_today, 2),
            places=2,
        )

    def test_spending_plan_at_retirement_spending_is_deflated(self) -> None:
        policy = {
            "identity": {"policy_base_currency": "BRL"},
            "objectives": [
                {
                    "id": "retirement",
                    "kind": "retirement",
                    "priority": "must_have",
                    "target_date": "2036-01-01",
                }
            ],
            "spending_plan": {
                "basis": "at_retirement",
                "default_inflation_pct": 2.0,
                "essentials": {"annual_amount": {"amount": 121_000, "currency": "BRL"}},
            },
            "retirement_assumptions": {
                "withdrawal_rule": {"method": "fixed_pct_swr", "initial_rate_pct": 4.0},
                "target_real_return_pct": 0.0,
            },
        }

        summary = compute_funded_ratios(
            0, policy, base_currency="BRL", as_of="2026-01-01"
        )

        years = 3652 / 365.25
        expected_today = 121_000 / (1.02**years) / 0.04
        self.assertAlmostEqual(
            summary.results[0].target_amount_today_base or 0.0,
            round(expected_today, 2),
            places=2,
        )


class FundedRatioCliTests(unittest.TestCase):
    def test_funded_ratio_cli_requests_policy_only_fx_currencies(self) -> None:
        from rikdom.cli import cmd_funded_ratio

        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [
                {
                    "id": "brl-cash",
                    "asset_type_id": "cash",
                    "market_value": {"amount": 10_000, "currency": "BRL"},
                }
            ],
        }
        policy = {
            "identity": {"policy_base_currency": "BRL"},
            "objectives": [
                {
                    "id": "education",
                    "kind": "education",
                    "priority": "important",
                    "target_amount": {"amount": 10_000, "currency": "USD"},
                    "target_date": "2026-01-01",
                }
            ],
            "cashflow_policy": {
                "contributions": [
                    {
                        "amount": {"amount": 100, "currency": "EUR"},
                        "cadence": {"frequency": "monthly"},
                    }
                ]
            },
        }
        lock = {
            "base_currency": "BRL",
            "rates_to_base": {"USD": 5.0, "EUR": 6.0},
        }
        aggregate = SimpleNamespace(
            total_value_base=10_000,
            base_currency="BRL",
            by_account={},
            warnings=[],
            errors=[],
        )
        args = Namespace(
            portfolio="portfolio.json",
            policy="policy.json",
            fx_history="fx.jsonl",
            as_of="2026-01-01",
            strict_quality=False,
        )

        with (
            mock.patch("rikdom.cli.load_json", side_effect=[portfolio, policy]),
            mock.patch("rikdom.cli.validate_policy", return_value=[]),
            mock.patch(
                "rikdom.cli.ensure_snapshot_fx_lock", return_value=(lock, [])
            ) as mock_fx,
            mock.patch("rikdom.cli.aggregate_portfolio", return_value=aggregate),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            rc = cmd_funded_ratio(args)

        self.assertEqual(rc, 0)
        self.assertEqual(
            mock_fx.call_args.kwargs["extra_quote_currencies"], ["EUR", "USD"]
        )

    def test_cli_runs_against_sample(self) -> None:
        from rikdom.cli import main

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            portfolio_dst = tmp_path / "portfolio.json"
            policy_dst = tmp_path / "policy.json"
            fx_dst = tmp_path / "fx_rates.jsonl"
            portfolio_dst.write_bytes(Path("data-sample/portfolio.json").read_bytes())
            policy_dst.write_bytes(Path("data-sample/policy.json").read_bytes())
            fx_dst.write_bytes(Path("data-sample/fx_rates.jsonl").read_bytes())

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(
                    [
                        "funded-ratio",
                        "--portfolio",
                        str(portfolio_dst),
                        "--policy",
                        str(policy_dst),
                        "--fx-history",
                        str(fx_dst),
                        "--as-of",
                        "2026-04-19",
                    ]
                )

        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["base_currency"], "BRL")
        self.assertGreater(payload["portfolio_value_base"], 0)
        objective_ids = {obj["objective_id"] for obj in payload["objectives"]}
        self.assertIn("retirement", objective_ids)
        self.assertIn("emergency", objective_ids)


if __name__ == "__main__":
    unittest.main()
