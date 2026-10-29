"""Literal monetary examples; FIFO must reconcile period change, not lifetime gain."""

import copy
import math
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rikdom.performance import compute_performance
from rikdom import profit_attribution
from rikdom.historical_fx import HistoricalFx
from rikdom.market_series import load_market_series
from tests.test_historical_fx import FIRST, fx_document
from rikdom.profit_attribution import compute_profit_attribution

START = "2026-01-01T00:00:00Z"
END = "2026-02-01T00:00:00Z"


def event(aid, kind, amount, day=15, **extra):
    return {
        "id": aid,
        "event_type": kind,
        "effective_at": f"2026-01-{day:02}T12:00:00Z",
        "account_id": "a",
        "holding_id": "h",
        "money": {"amount": amount, "currency": "BRL"},
        **extra,
    }


def portfolio(activities=None):
    return {
        "schema_version": "2.0.0",
        "base_currency": "BRL",
        "activities": activities or [],
    }


def performance(p, closing=280, opening=200):
    snapshots = [
        {
            "timestamp": date,
            "base_currency": "BRL",
            "totals": {"portfolio_value_base": value},
        }
        for date, value in [(START, opening), (END, closing)]
    ]
    return compute_performance(snapshots, p["activities"], base_currency="BRL")


def evidence():
    return {
        "contract_version": "1.0",
        "scope": "portfolio",
        "base_currency": "BRL",
        "period_start": START,
        "period_end": END,
        "method": "fifo",
        "price_adjustment": "unadjusted",
        "cost_convention": "buy_costs_capitalized_sell_costs_deducted",
        "review": {
            "status": "reviewed",
            "source": "synthetic reviewed statement",
            "reviewed_at": "2026-02-02T00:00:00Z",
            "retrieved_before": "2026-02-02T00:00:00Z",
        },
        "history": {
            "status": "complete",
            "from": START,
            "through": END,
            "missing_periods": [],
        },
        "opening_cash_base": 80,
        "closing_cash_base": 214,
        "opening_lots": [
            {
                "id": "old",
                "account_id": "a",
                "holding_id": "h",
                "currency": "BRL",
                "acquired_at": "2025-01-01T00:00:00Z",
                "quantity": 10,
                "total_cost_native": 100,
            }
        ],
        "opening_positions": [
            {
                "account_id": "a",
                "holding_id": "h",
                "currency": "BRL",
                "quantity": 10,
                "market_value_native": 120,
            }
        ],
        "closing_positions": [
            {
                "account_id": "a",
                "holding_id": "h",
                "currency": "BRL",
                "quantity": 3,
                "market_value_native": 66,
            }
        ],
    }


def trades():
    return [
        event("buy", "buy", 75, 5, quantity=5, fees={"amount": 5, "currency": "BRL"}),
        event(
            "sell",
            "sell",
            216,
            10,
            quantity=12,
            fees={"amount": 6, "currency": "BRL"},
            withholding_tax={"amount": 2, "currency": "BRL"},
        ),
        event(
            "income",
            "dividend",
            10,
            15,
            metadata={"rikdom_income": {"version": 1, "amount_basis": "net"}},
            fees={"amount": 1, "currency": "BRL"},
            withholding_tax={"amount": 2, "currency": "BRL"},
        ),
        event("fee", "fee", 3, 20),
        event("tax", "tax_withheld", 1, 21),
    ]


class ProfitAttributionTests(unittest.TestCase):
    def test_strict_basis_reader_rejects_duplicates_and_nonfinite_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "basis.json"
            path.write_text(json.dumps(evidence()))
            self.assertEqual(profit_attribution.load_profit_basis(path), evidence())
            for text in [
                '{"review": 1, "review": 2}',
                '{"x":NaN}',
                '{"x":1e999}',
                "[]",
            ]:
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    profit_attribution.load_profit_basis(path)

    def test_canonical_settings_currency_mismatch_blocks_bridge(self):
        p = portfolio([])
        p.pop("base_currency")
        p["settings"] = {"base_currency": "USD"}
        self.assertEqual(
            compute_profit_attribution(p, performance(p))["status"], "unavailable"
        )

    def test_dated_foreign_external_flow_retains_source_and_does_not_imply_fifo_fx(
        self,
    ):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fx.json"
            path.write_text(json.dumps(fx_document()))
            fx = HistoricalFx(
                load_market_series(path),
                base_currency="BRL",
                series_by_currency={"USD": "usd-brl"},
                max_age_seconds=86400,
            )
            p = portfolio(
                [
                    event(
                        "foreign",
                        "contribution",
                        10,
                        effective_at=FIRST,
                        money={"amount": 10, "currency": "USD"},
                    )
                ]
            )
            snapshots = [
                {
                    "timestamp": d,
                    "base_currency": "BRL",
                    "totals": {"portfolio_value_base": v},
                }
                for d, v in [(START, 200), (END, 280)]
            ]
            perf = compute_performance(
                snapshots, p["activities"], base_currency="BRL", historical_fx=fx
            )
            result = compute_profit_attribution(
                p, perf, historical_fx=fx, basis=evidence()
            )
            self.assertEqual(result["bridge"]["investment_result_base"], 30)
            self.assertEqual(
                result["bridge"]["cashflow_evidence"][0]["amount_base"], 50
            )
            self.assertEqual(
                result["bridge"]["cashflow_evidence"][0]["fx_evidence"]["observation"][
                    "source"
                ],
                "synthetic",
            )
            self.assertEqual(result["decomposition"]["status"], "unavailable")
            self.assertEqual(
                compute_profit_attribution(p, perf)["status"], "unavailable"
            )

    def test_fifo_with_cash_only_external_flows_reconciles(self):
        p = portfolio(
            [
                *trades(),
                event("contribution", "contribution", 50, holding_id=None),
                event("withdrawal", "withdrawal", 20, holding_id=None),
            ]
        )
        basis = evidence()
        basis["closing_cash_base"] = 244
        result = compute_profit_attribution(p, performance(p, closing=310), basis=basis)
        self.assertEqual(
            result["decomposition"]["status"], "complete", result["diagnostics"]
        )
        self.assertEqual(result["decomposition"]["explained_result_base"], 80)

    def test_nontrade_quantity_and_stale_performance_fx_do_not_claim_completeness(self):
        acts = trades()
        acts[2]["quantity"] = 5
        p = portfolio(acts)
        self.assertEqual(
            compute_profit_attribution(p, performance(p), basis=evidence())[
                "decomposition"
            ]["status"],
            "unavailable",
        )
        p = portfolio([])
        perf = performance(p)
        perf.fx_status = "unavailable"
        self.assertEqual(compute_profit_attribution(p, perf)["status"], "unavailable")

    def test_unverified_snapshot_currencies_and_zero_window_block_bridge(self):
        p = portfolio([])
        for currency in [None, "USD"]:
            snapshots = [
                {
                    "timestamp": d,
                    "totals": {"portfolio_value_base": 200},
                    **({"base_currency": currency} if currency is not None else {}),
                }
                for d in [START, END]
            ]
            perf = compute_performance(snapshots, [], base_currency="BRL")
            self.assertEqual(
                compute_profit_attribution(p, perf)["status"], "unavailable"
            )
        perf = performance(p)
        perf.period_end = START
        self.assertEqual(compute_profit_attribution(p, perf)["status"], "unavailable")

    def test_cross_account_fifo_inventory_cannot_cover_a_sale(self):
        p = portfolio(trades())
        basis = evidence()
        basis["opening_lots"][0]["account_id"] = "other"
        self.assertEqual(
            compute_profit_attribution(p, performance(p), basis=basis)["decomposition"][
                "status"
            ],
            "unavailable",
        )

    def test_cost_basis_adjustments_on_supported_events_block_fifo(self):
        for index in (1, 2):
            for adjustment in (10, 0, -10):
                acts = trades()
                acts[index]["cost_basis_adjustment"] = {
                    "amount": adjustment,
                    "currency": "BRL",
                }
                p = portfolio(acts)
                with self.subTest(
                    event=acts[index]["event_type"], adjustment=adjustment
                ):
                    result = compute_profit_attribution(
                        p, performance(p), basis=evidence()
                    )
                    self.assertEqual(result["bridge"]["investment_result_base"], 80)
                    self.assertEqual(result["decomposition"]["status"], "unavailable")
                    self.assertIsNone(result["decomposition"]["realized_gain_base"])
                    self.assertTrue(
                        any(
                            "cost_basis_adjustment" in message
                            for message in result["diagnostics"]
                        )
                    )

    def test_period_evidence_after_cutoff_or_with_invalid_knowledge_dates_blocks_fifo(
        self,
    ):
        for field in ("ingested_at", "created_at"):
            for timestamp in (
                "2026-03-01T00:00:00Z",
                "bad",
                "2026-02-01T12:00:00",
                None,
            ):
                acts = trades()
                acts[2][field] = timestamp
                p = portfolio(acts)
                with self.subTest(field=field, timestamp=timestamp):
                    result = compute_profit_attribution(
                        p, performance(p), basis=evidence()
                    )
                    self.assertEqual(result["bridge"]["investment_result_base"], 80)
                    self.assertEqual(result["decomposition"]["status"], "unavailable")
                    self.assertIsNone(result["decomposition"]["explained_result_base"])
                    self.assertTrue(
                        any(
                            "income" in message and field in message
                            for message in result["diagnostics"]
                        )
                    )

    def test_post_cutoff_corrected_receipt_cannot_satisfy_earlier_review(self):
        acts = trades()
        original = copy.deepcopy(acts[2])
        original.update(id="old-income", ingested_at="2026-02-01T00:00:00Z")
        original["money"]["amount"] = 9
        acts[2]["ingested_at"] = "2026-03-01T00:00:00Z"
        acts[2]["extensions"] = {
            "rikdom_correction": {
                "version": 1,
                "supersedes_activity_id": "old-income",
                "reason": "synthetic late correction",
            }
        }
        p = portfolio([original, *acts])
        result = compute_profit_attribution(p, performance(p), basis=evidence())
        self.assertEqual(result["bridge"]["investment_result_base"], 80)
        self.assertEqual(result["decomposition"]["status"], "unavailable")
        self.assertTrue(
            any(
                "income" in message and "cutoff" in message
                for message in result["diagnostics"]
            )
        )

    def test_raw_correction_lineage_cannot_hide_late_or_malformed_evidence(self):
        for late_row in ("superseded", "intermediate", "cancelled", "shifted"):
            original = event("old-extra", "dividend", 999)
            correction = event(
                "new-extra",
                "dividend",
                999,
                ingested_at="2026-03-01T00:00:00Z",
                extensions={
                    "rikdom_correction": {
                        "version": 1,
                        "supersedes_activity_id": "old-extra",
                        "reason": "synthetic",
                    }
                },
            )
            acts = trades()
            if late_row == "superseded":
                original = copy.deepcopy(acts[2])
                original.update(id="old-extra", ingested_at="2026-03-01T00:00:00Z")
                acts[2]["extensions"] = correction["extensions"]
                acts[2]["ingested_at"] = "2026-02-01T00:00:00Z"
                p = portfolio([original, *acts])
            elif late_row == "intermediate":
                original = copy.deepcopy(acts[2])
                original["id"] = "old-extra"
                correction["money"]["amount"] = 10
                correction["metadata"] = copy.deepcopy(acts[2]["metadata"])
                acts[2]["extensions"] = {
                    "rikdom_correction": {
                        "version": 1,
                        "supersedes_activity_id": "new-extra",
                        "reason": "synthetic second correction",
                    }
                }
                p = portfolio([original, correction, *acts])
            else:
                correction["effective_at"] = "2026-03-01T00:00:00Z"
                if late_row == "cancelled":
                    correction["status"] = "cancelled"
                    correction["ingested_at"] = "not-a-date"
                p = portfolio([original, correction, *acts])
            with self.subTest(late_row=late_row):
                result = compute_profit_attribution(p, performance(p), basis=evidence())
                self.assertEqual(result["bridge"]["status"], "complete")
                self.assertEqual(result["decomposition"]["status"], "unavailable")
                self.assertTrue(result["diagnostics"])

    def test_accepted_cutoff_retains_raw_lineage_provenance_and_ignores_unrelated_future(
        self,
    ):
        acts = trades()
        original = copy.deepcopy(acts[2])
        original["id"] = "old-income"
        original["ingested_at"] = "2026-02-01T00:00:00Z"
        acts[2]["extensions"] = {
            "rikdom_correction": {
                "version": 1,
                "supersedes_activity_id": "old-income",
                "reason": "synthetic reviewed correction",
            }
        }
        acts[2]["ingested_at"] = "2026-02-02T00:00:00Z"
        acts[2]["source_system"] = "synthetic-source"
        unrelated = event(
            "future",
            "dividend",
            999,
            effective_at="2026-03-01T00:00:00Z",
            ingested_at="2026-03-02T00:00:00Z",
        )
        p = portfolio([original, *acts, unrelated])
        before = copy.deepcopy(p)
        result = compute_profit_attribution(p, performance(p), basis=evidence())
        self.assertEqual(
            result["decomposition"]["status"], "complete", result["diagnostics"]
        )
        audit = result["decomposition"]["history_evidence"]
        self.assertEqual(audit["retrieved_before"], "2026-02-02T00:00:00Z")
        self.assertEqual(
            {row["id"] for row in audit["activities"]},
            {"old-income", "buy", "sell", "income", "fee", "tax"},
        )
        accepted = next(row for row in audit["activities"] if row["id"] == "income")
        self.assertEqual(accepted["source_system"], "synthetic-source")
        self.assertEqual(
            accepted["extensions"]["rikdom_correction"]["supersedes_activity_id"],
            "old-income",
        )
        accepted["source_system"] = "modified output"
        self.assertEqual(p, before)

    def test_signed_flow_bridge_is_period_residual_without_basis(self):
        p = portfolio(
            [event("in", "contribution", 50), event("out", "withdrawal", -20)]
        )
        result = compute_profit_attribution(p, performance(p, closing=310))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["return_basis"], "period")
        self.assertEqual(result["bridge"]["opening_value_base"], 200)
        self.assertEqual(result["bridge"]["net_external_cashflow_base"], 30)
        self.assertEqual(result["bridge"]["investment_result_base"], 80)
        self.assertEqual(result["bridge"]["closing_value_base"], 310)
        self.assertEqual(result["decomposition"]["status"], "unavailable")
        self.assertIsNone(result["decomposition"]["realized_gain_base"])

    def test_fifo_capitalizes_buy_costs_deducts_sell_costs_and_uses_unrealized_change(
        self,
    ):
        p, basis = portfolio(trades()), evidence()
        before = copy.deepcopy((p, basis))
        result = compute_profit_attribution(p, performance(p), basis=basis)
        d = result["decomposition"]
        self.assertEqual(d["status"], "complete", result["diagnostics"])
        self.assertEqual(d["realized_gain_base"], 76)  # 216-6-2 - (100+2*16)
        self.assertEqual(d["opening_unrealized_gain_base"], 20)
        self.assertEqual(d["closing_unrealized_gain_base"], 18)  # 66 - 3*16
        self.assertEqual(d["unrealized_change_base"], -2)
        self.assertEqual(d["net_income_base"], 10)  # already net; don't deduct twice
        self.assertEqual(d["standalone_fees_base"], 3)
        self.assertEqual(d["standalone_taxes_base"], 1)
        self.assertEqual(d["explained_result_base"], 80)
        self.assertEqual(d["reconciliation_difference_base"], 0)
        sell = next(
            row for row in d["activity_evidence"] if row["activity_id"] == "sell"
        )
        self.assertEqual(sell["cost_removed_native"], 132)
        self.assertEqual(
            sell["consumed_lots"],
            [
                {"lot_id": "old", "quantity": 10, "cost_native": 100},
                {"lot_id": "buy", "quantity": 2, "cost_native": 32},
            ],
        )
        self.assertEqual((p, basis), before)
        self.assertEqual(
            compute_profit_attribution(p, performance(p), basis=basis), result
        )

    def test_gross_income_costs_are_deducted_once(self):
        acts = trades()
        acts[2]["money"]["amount"] = 13
        acts[2].pop("metadata")
        p = portfolio(acts)
        result = compute_profit_attribution(p, performance(p), basis=evidence())
        self.assertEqual(result["decomposition"]["net_income_base"], 10)
        self.assertEqual(result["decomposition"]["status"], "complete")

    def test_corrected_and_idempotent_income_uses_effective_ledger(self):
        acts = trades()
        old = event("wrong", "dividend", 999)
        acts[2]["extensions"] = {
            "rikdom_correction": {
                "version": 1,
                "supersedes_activity_id": "wrong",
                "reason": "synthetic correction",
            }
        }
        p = portfolio([old, *acts])
        self.assertEqual(
            compute_profit_attribution(p, performance(p), basis=evidence())[
                "decomposition"
            ]["net_income_base"],
            10,
        )
        acts = trades()
        acts[2]["idempotency_key"] = "same-income"
        duplicate = {
            **copy.deepcopy(acts[2]),
            "id": "second-import",
            "import_run_id": "rerun",
        }
        p = portfolio(
            [*acts, duplicate, event("cancelled", "dividend", 999, status="cancelled")]
        )
        self.assertEqual(
            compute_profit_attribution(p, performance(p), basis=evidence())[
                "decomposition"
            ]["status"],
            "complete",
        )

    def test_missing_or_unreviewed_basis_never_claims_realized_profit(self):
        for change in [
            {"review": {"status": "unreviewed"}},
            {"history": {"status": "partial"}},
            {"price_adjustment": "split_adjusted"},
            {"unexpected": True},
        ]:
            with self.subTest(change=change):
                basis = evidence() | change
                p = portfolio(trades())
                result = compute_profit_attribution(p, performance(p), basis=basis)
                self.assertEqual(result["bridge"]["investment_result_base"], 80)
                self.assertEqual(result["decomposition"]["status"], "unavailable")
                self.assertIsNone(result["decomposition"]["realized_gain_base"])

    def test_oversell_and_wrong_terminal_quantity_are_unavailable(self):
        for quantity in [16, 11]:
            acts = trades()
            acts[1]["quantity"] = quantity
            p = portfolio(acts)
            result = compute_profit_attribution(p, performance(p), basis=evidence())
            self.assertEqual(result["decomposition"]["status"], "unavailable")
            self.assertTrue(result["diagnostics"])

    def test_unsupported_movements_and_corporate_actions_are_unavailable(self):
        for kind in [
            "split",
            "merger",
            "amortization",
            "reimbursement",
            "fx_conversion",
            "other",
        ]:
            p = portfolio([*trades(), event("unsupported", kind, 0)])
            result = compute_profit_attribution(p, performance(p), basis=evidence())
            self.assertEqual(result["decomposition"]["status"], "unavailable", kind)
            self.assertIsNone(result["decomposition"]["explained_result_base"])

    def test_currency_cost_date_and_history_mismatches_are_unavailable(self):
        variants = []
        b = evidence()
        b["closing_positions"][0]["currency"] = "USD"
        variants.append((trades(), b))
        b = evidence()
        b["period_end"] = "2026-02-02T00:00:00Z"
        variants.append((trades(), b))
        b = evidence()
        b["history"]["missing_periods"] = ["2026-01-15"]
        variants.append((trades(), b))
        a = trades()
        a[0]["fees"]["currency"] = "USD"
        variants.append((a, evidence()))
        a = trades()
        a[0]["effective_at"] = START
        variants.append((a, evidence()))
        a = trades()
        a[2]["metadata"]["rikdom_income"]["amount_basis"] = "unknown"
        variants.append((a, evidence()))
        a = trades()
        a[1]["corporate_action"] = {"legs": []}
        variants.append((a, evidence()))
        for acts, b in variants:
            with self.subTest(acts=acts, basis=b):
                p = portfolio(acts)
                result = compute_profit_attribution(p, performance(p), basis=b)
                self.assertEqual(result["decomposition"]["status"], "unavailable")

    def test_bookend_and_cash_reconciliation_cannot_be_fabricated(self):
        b = evidence()
        b["closing_cash_base"] = 215
        p = portfolio(trades())
        result = compute_profit_attribution(p, performance(p), basis=b)
        self.assertEqual(result["decomposition"]["status"], "unavailable")
        self.assertIsNone(result["decomposition"]["realized_gain_base"])

    def test_unavailable_malformed_and_mismatched_external_inputs_block_bridge(self):
        for act in [
            event("bad", "contribution", 10, money={"amount": 10, "currency": "USD"}),
            event("bad", "contribution", math.inf),
            event("bad", "contribution", 10, effective_at="bad"),
            event("bad", "transfer_in", 10),
        ]:
            p = portfolio([act])
            result = compute_profit_attribution(p, performance(p))
            self.assertEqual(result["bridge"]["status"], "unavailable", act)
            self.assertIsNone(result["bridge"]["investment_result_base"])
        p = portfolio([])
        perf = performance(p)
        perf.net_external_cashflow_base = None
        self.assertEqual(compute_profit_attribution(p, perf)["status"], "unavailable")
        perf = performance(p)
        perf.net_external_cashflow_base = 42
        self.assertEqual(compute_profit_attribution(p, perf)["status"], "unavailable")

    def test_conflicting_duplicate_events_do_not_yield_complete_totals(self):
        acts = trades()
        p = portfolio([*acts, {**acts[2], "money": {"amount": 999, "currency": "BRL"}}])
        result = compute_profit_attribution(p, performance(p), basis=evidence())
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["bridge"]["investment_result_base"])

    def test_invalid_missing_snapshot_and_currency_mismatch_do_not_look_complete(self):
        p = portfolio([])
        perf = compute_performance([], [], base_currency="BRL")
        self.assertEqual(compute_profit_attribution(p, perf)["status"], "unavailable")
        for opening in [-1, math.inf]:
            self.assertEqual(
                compute_profit_attribution(p, performance(p, opening=opening))[
                    "status"
                ],
                "unavailable",
            )
        p["base_currency"] = "USD"
        self.assertEqual(
            compute_profit_attribution(p, performance(p))["status"], "unavailable"
        )


if __name__ == "__main__":
    unittest.main()
