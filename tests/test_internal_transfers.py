"""Hand-checkable explicit cash-pair boundary and identity examples."""

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rikdom.performance import (
    compute_performance,
    compute_performance_by_account,
    compute_performance_by_strategic_bucket,
    extract_external_cashflows,
    performance_result_to_dict,
)
from rikdom.profit_attribution import compute_profit_attribution
from rikdom.historical_fx import HistoricalFx
from rikdom.market_series import load_market_series
from tests.test_historical_fx import FIRST, fx_document
from tests.test_profit_attribution import evidence, trades, portfolio, performance

START = "2026-01-01T00:00:00Z"
END = "2026-02-01T00:00:00Z"
MID = "2026-01-16T12:00:00Z"


def pair():
    claim = {
        "version": 1,
        "pair_id": "bank-move-17",
        "review": {
            "status": "reviewed",
            "source": "Both bank statements",
            "reviewed_at": "2026-02-02T00:00:00Z",
        },
    }
    return [
        {
            "id": aid,
            "event_type": kind,
            "account_id": account,
            "effective_at": MID,
            "status": "posted",
            "money": {"amount": 20, "currency": "BRL"},
            "metadata": {"rikdom_internal_transfer": copy.deepcopy(claim)},
        }
        for aid, kind, account in [
            ("out", "transfer_out", "a"),
            ("in", "transfer_in", "b"),
        ]
    ]


def snapshots():
    return [
        {
            "timestamp": when,
            "base_currency": "BRL",
            "totals": {
                "portfolio_value_base": total,
                "by_account": accounts,
                "by_strategic_bucket": {"__unallocated__": total},
            },
        }
        for when, total, accounts in [
            (START, 100, {"a": 60, "b": 40}),
            (END, 110, {"a": 46, "b": 64}),
        ]
    ]


class InternalTransferTests(unittest.TestCase):
    def compute(self, rows):
        return compute_performance(snapshots(), rows, base_currency="BRL")

    def test_verified_pair_suppressed_only_at_portfolio_boundary(self):
        rows = pair()
        result = self.compute(rows)
        self.assertEqual(result.cashflow_count, 0)
        self.assertEqual(result.net_external_cashflow_base, 0)
        self.assertEqual(result.twr_method, "bookend_ratio")
        self.assertEqual(result.twr_return_pct, 10)
        self.assertEqual(result.growth_bridge["status"], "complete")
        accounts, _ = compute_performance_by_account(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertEqual([r.cashflow_count for r in accounts], [1, 1])
        self.assertEqual([r.net_external_cashflow_base for r in accounts], [-20, 20])
        self.assertEqual([r.twr_pct for r in accounts], [12, 8])
        buckets, _ = compute_performance_by_strategic_bucket(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertEqual(buckets[0].cashflow_count, 2)
        self.assertEqual(buckets[0].twr_pct, 10)

    def test_external_contribution_remains_external(self):
        rows = pair() + [
            {
                "id": "deposit",
                "event_type": "contribution",
                "effective_at": MID,
                "money": {"amount": 10, "currency": "BRL"},
            }
        ]
        result = self.compute(rows)
        self.assertEqual(result.cashflow_count, 1)
        self.assertEqual(result.net_external_cashflow_base, 10)
        self.assertEqual(result.twr_return_pct, 0)

    def test_similarity_without_identity_is_never_pairing(self):
        rows = pair()
        for row in rows:
            row.pop("metadata")
        result = self.compute(rows)
        self.assertEqual(result.cashflow_count, 2)
        self.assertEqual(result.twr_method, "modified_dietz")
        self.assertTrue(any("unresolved" in w.lower() for w in result.warnings))
        self.assertEqual(result.growth_bridge["status"], "unavailable")

    def test_invalid_claims_cannot_improve_returns(self):
        mutations = [
            lambda rows: rows.pop(),
            lambda rows: rows.append({**copy.deepcopy(rows[1]), "id": "third"}),
            lambda rows: rows[1].update(account_id="a"),
            lambda rows: rows[1].update(effective_at="2026-01-17T12:00:00Z"),
            lambda rows: rows[1]["money"].update(amount=21),
            lambda rows: rows[1]["money"].update(currency="USD"),
            lambda rows: rows[1].update(status="cancelled"),
            lambda rows: rows[1].update(holding_id="asset"),
            lambda rows: rows[1].update(quantity=1),
            lambda rows: rows[1].update(tax_lot_ids=["lot-17"]),
            lambda rows: rows[1].update(fees={"amount": 1, "currency": "BRL"}),
            lambda rows: rows[1]["metadata"]["rikdom_internal_transfer"].update(
                version=True
            ),
            lambda rows: rows[1]["metadata"]["rikdom_internal_transfer"][
                "review"
            ].update(status="unreviewed"),
            lambda rows: rows[1]["metadata"]["rikdom_internal_transfer"][
                "review"
            ].update(reviewed_at="2026-02-02"),
            lambda rows: rows[1]["metadata"].update(rikdom_internal_transfer=None),
            lambda rows: rows[1].update(id="out"),
            lambda rows: rows[1].pop("id"),
            lambda rows: rows[1]["money"].update(amount=True),
        ]
        for mutation in mutations:
            rows = pair()
            mutation(rows)
            with self.subTest(rows=rows):
                result = self.compute(rows)
                self.assertIsNone(result.twr_pct)
                self.assertIsNone(result.twr_return_pct)
                self.assertIsNone(result.mwr_pct)
                self.assertEqual(result.growth_bridge["status"], "unavailable")
                self.assertEqual(
                    performance_result_to_dict(result)["internal_transfers"]["status"],
                    "unavailable",
                )

    def test_identical_duplicate_rows_are_deduplicated(self):
        rows = pair()
        rows.append(copy.deepcopy(rows[0]))
        self.assertEqual(self.compute(rows).cashflow_count, 0)
        accounts, _ = compute_performance_by_account(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertEqual([r.cashflow_count for r in accounts], [1, 1])

    def test_conflicting_duplicate_unclaimed_identity_invalidates_pair(self):
        rows = pair()
        conflict = copy.deepcopy(rows[0])
        conflict.pop("metadata")
        conflict["money"]["amount"] = 100
        rows.append(conflict)
        self.assertIsNone(self.compute(rows).twr_return_pct)

    def test_correction_replaces_one_leg_before_matching(self):
        rows = pair()
        rows[0]["money"]["amount"] = 19
        replacement = copy.deepcopy(rows[0])
        replacement.update(
            id="out-corrected",
            money={"amount": 20, "currency": "BRL"},
            extensions={
                "rikdom_correction": {
                    "version": 1,
                    "supersedes_activity_id": "out",
                    "reason": "statement correction",
                }
            },
        )
        result = self.compute(rows + [replacement])
        self.assertEqual(result.cashflow_count, 0)
        ids = performance_result_to_dict(result)["internal_transfers"]["pairs"][0][
            "activity_ids"
        ]
        self.assertEqual(set(ids), {"out-corrected", "in"})
        replacement["status"] = "cancelled"
        self.assertIsNone(self.compute(rows + [replacement]).twr_return_pct)

    def test_pair_validation_precedes_period_filter(self):
        rows = pair()
        rows[1]["effective_at"] = "2026-02-02T00:00:00Z"
        self.assertIsNone(self.compute(rows).twr_return_pct)
        rows = pair()
        for row in rows:
            row["effective_at"] = START
        self.assertEqual(self.compute(rows).cashflow_count, 0)
        for row in rows:
            row["effective_at"] = END
        self.assertEqual(self.compute(rows).cashflow_count, 0)
        for row in rows:
            row["effective_at"] = "2026-02-02T00:00:00Z"
        rows.pop()
        self.assertEqual(self.compute(rows).twr_method, "bookend_ratio")

    def test_foreign_cash_pair_needs_no_portfolio_conversion(self):
        rows = pair()
        for row in rows:
            row["money"]["currency"] = "USD"
        result = self.compute(rows)
        self.assertEqual(result.twr_method, "bookend_ratio")
        self.assertEqual(result.cashflow_count, 0)
        self.assertEqual(extract_external_cashflows(rows, "BRL"), ([], []))

    def test_foreign_pair_still_needs_scoped_conversion(self):
        rows = pair()
        for row in rows:
            row["money"]["currency"] = "USD"
        accounts, _ = compute_performance_by_account(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertTrue(all(row.twr_pct is None for row in accounts))
        buckets, _ = compute_performance_by_strategic_bucket(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertTrue(all(row.twr_pct is None for row in buckets))
        accounts, _ = compute_performance_by_account(
            snapshots(), rows, base_currency="BRL", fx_rates_to_base={"USD": 1}
        )
        self.assertEqual(
            [row.net_external_cashflow_base for row in accounts], [-20, 20]
        )

    def test_idempotency_replay_deduplicates_before_pairing(self):
        rows = pair()
        rows[0]["idempotency_key"] = "statement:17:out"
        replay = copy.deepcopy(rows[0])
        replay.update(id="out-reimport", import_run_id="second-import")
        self.assertEqual(self.compute(rows + [replay]).cashflow_count, 0)
        replay["money"]["amount"] = 30
        self.assertIsNone(self.compute(rows + [replay]).twr_return_pct)

    def test_bad_claim_disables_scoped_returns(self):
        rows = pair()[:1]
        accounts, _ = compute_performance_by_account(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertIsNone(accounts[0].twr_pct)
        buckets, _ = compute_performance_by_strategic_bucket(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertIsNone(buckets[0].twr_pct)

    def test_invalid_claim_date_cannot_disappear_from_scopes(self):
        rows = pair()
        rows[0]["effective_at"] = "not-a-timestamp"
        accounts, _ = compute_performance_by_account(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertTrue(all(row.twr_pct is None for row in accounts))
        buckets, _ = compute_performance_by_strategic_bucket(
            snapshots(), rows, base_currency="BRL"
        )
        self.assertTrue(all(row.twr_pct is None for row in buckets))

    def test_import_run_metadata_does_not_duplicate_a_stable_leg(self):
        rows = pair()
        replay = copy.deepcopy(rows[0])
        replay.update(import_run_id="replay", ingested_at="2026-02-02T00:00:00Z")
        self.assertEqual(self.compute(rows + [replay]).cashflow_count, 0)

    def test_equal_utc_instants_and_zero_costs_are_cash_pairs(self):
        rows = pair()
        rows[1]["effective_at"] = "2026-01-16T09:00:00-03:00"
        rows[0]["quantity"] = 0
        rows[0]["fees"] = {"amount": 0, "currency": "BRL"}
        self.assertEqual(self.compute(rows).twr_method, "bookend_ratio")

    def test_dated_fx_converts_scope_legs_after_portfolio_resolution(self):
        rows = pair()
        for row in rows:
            row["effective_at"] = FIRST
            row["money"]["currency"] = "USD"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fx.json"
            path.write_text(json.dumps(fx_document()))
            fx = HistoricalFx(
                load_market_series(path),
                base_currency="BRL",
                series_by_currency={"USD": "usd-brl"},
                max_age_seconds=86400,
            )
            result = compute_performance(
                snapshots(), rows, base_currency="BRL", historical_fx=fx
            )
            self.assertEqual(result.twr_method, "bookend_ratio")
            self.assertEqual(result.fx_evidence, [])
            accounts, _ = compute_performance_by_account(
                snapshots(), rows, base_currency="BRL", historical_fx=fx
            )
            self.assertEqual(
                [row.net_external_cashflow_base for row in accounts], [-100, 100]
            )
            self.assertEqual([row.cashflow_count for row in accounts], [1, 1])
            self.assertFalse(
                any(
                    "unresolved" in warning
                    for row in accounts
                    for warning in row.warnings
                )
            )

    def test_foreign_cash_pairs_do_not_claim_fifo_fx_completeness(self):
        rows = pair()
        for row in rows:
            row["money"]["currency"] = "USD"
        p = portfolio(trades() + rows)
        result = compute_profit_attribution(p, performance(p), basis=evidence())
        self.assertEqual(result["bridge"]["status"], "complete")
        self.assertEqual(result["decomposition"]["status"], "unavailable")
        self.assertIsNone(result["decomposition"]["realized_gain_base"])

    def test_output_provenance_is_detached_from_inputs_and_result(self):
        rows = pair()
        before = copy.deepcopy(rows)
        result = self.compute(rows)
        output = performance_result_to_dict(result)
        self.assertEqual(rows, before)
        self.assertEqual(
            output["internal_transfers"]["pairs"][0]["pair_id"], "bank-move-17"
        )
        output["internal_transfers"]["pairs"][0]["review"]["source"] = "changed"
        output["internal_transfers"]["pairs"][0]["activity_ids"].append("changed")
        self.assertEqual(rows, before)
        fresh = performance_result_to_dict(result)["internal_transfers"]["pairs"][0]
        self.assertEqual(fresh["review"]["source"], "Both bank statements")
        self.assertEqual(len(fresh["activity_ids"]), 2)

    def test_profit_bridge_and_fifo_keep_pair_cash_legs_and_positions(self):
        p = portfolio(trades() + pair())
        result = compute_profit_attribution(p, performance(p), basis=evidence())
        self.assertEqual(result["bridge"]["status"], "complete", result["diagnostics"])
        self.assertEqual(
            result["decomposition"]["status"], "complete", result["diagnostics"]
        )
        self.assertEqual(result["bridge"]["investment_result_base"], 80)
        by_id = {
            r["activity_id"]: r for r in result["decomposition"]["activity_evidence"]
        }
        self.assertEqual(by_id["out"]["net_cash_native"], -20)
        self.assertEqual(by_id["in"]["net_cash_native"], 20)
        self.assertEqual(result["decomposition"]["realized_gain_base"], 76)
