from __future__ import annotations

import copy
import importlib
import json
import unittest


def _activity(event_type="buy", amount=100, *, id="buy-1", when="2025-01-01", **extra):
    activity = {
        "id": id,
        "holding_id": "h-fii",
        "event_type": event_type,
        "status": "posted",
        "effective_at": when,
        "instrument": {"ticker": "FII11"},
        "money": {"amount": amount, "currency": "BRL"},
    }
    if event_type == "buy":
        activity["quantity"] = 1
    activity.update(extra)
    return activity


def _portfolio(*activities):
    return {
        "settings": {"base_currency": "USD"},
        "holdings": [
            {
                "id": "h-fii",
                "identifiers": {"ticker": "FII11"},
                "quantity": 1,
                "as_of": "2026-01-01",
                "market_value": {"amount": 110, "currency": "BRL"},
                "extensions": {
                    "rikdom_instrument_history": {
                        "status": "complete",
                        "from": "2025-01-01",
                        "through": "2026-01-01",
                        "missing_periods": [],
                        "notes": [],
                    }
                },
            }
        ],
        "activities": list(activities) or [_activity()],
    }


class InstrumentPerformanceTests(unittest.TestCase):
    def compute(self, portfolio, **kwargs):
        try:
            module = importlib.import_module("rikdom.instrument_performance")
        except ModuleNotFoundError:
            self.fail("The instrument return calculator has not been implemented")
        return module.compute_instrument_performance(portfolio, "h-fii", **kwargs)

    def assert_incomplete(self, result):
        self.assertEqual(result["status"], "incomplete_history")
        self.assertIsNone(result["profit_amount"])
        self.assertIsNone(result["xirr_pct"])
        self.assertTrue(result["warnings"])

    def test_one_year_capital_gain_and_distribution_return_fifteen_percent(self):
        portfolio = _portfolio(
            _activity(), _activity("dividend", 5, id="div-1", when="2026-01-01")
        )
        original = copy.deepcopy(portfolio)
        result = self.compute(portfolio)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["currency"], "BRL")
        self.assertEqual(result["profit_amount"], 15)
        self.assertAlmostEqual(result["xirr_pct"], 15, places=7)
        self.assertEqual(result["observed_buy_outflows"], 100)
        self.assertEqual(result["observed_distributions"], 5)
        self.assertEqual(result["observed_net_cashflow"], -95)
        self.assertEqual(result["valuation_basis"], "gross_market_value")
        self.assertEqual(len(result["cashflows"]), 3)
        self.assertEqual(portfolio, original)
        json.dumps(result, allow_nan=False)

    def test_fees_and_retained_tax_reduce_investor_cashflows(self):
        portfolio = _portfolio(
            _activity(fees={"amount": 2, "currency": "BRL"}),
            _activity(
                "dividend",
                10,
                id="div",
                when="2026-01-01",
                fees={"amount": 1, "currency": "BRL"},
                withholding_tax={"amount": 2, "currency": "BRL"},
            ),
            _activity("fee", 1, id="fee", when="2026-01-01"),
            _activity("tax_withheld", 1, id="tax", when="2026-01-01"),
        )
        result = self.compute(portfolio)
        self.assertEqual(result["observed_buy_outflows"], 102)
        self.assertEqual(result["observed_distributions"], 7)
        self.assertEqual(result["observed_fees"], 4)
        self.assertEqual(result["observed_taxes"], 3)
        self.assertEqual(result["observed_net_cashflow"], -97)
        self.assertEqual(result["profit_amount"], 13)
        self.assertAlmostEqual(result["xirr_pct"], 100 * 13 / 102, places=7)

    def test_multiple_buys_use_each_actual_date(self):
        portfolio = _portfolio(
            _activity(), _activity(amount=100, id="buy-2", when="2025-07-02T12:00:00Z")
        )
        portfolio["holdings"][0].update(
            quantity=2, market_value={"amount": 231, "currency": "BRL"}
        )
        result = self.compute(portfolio)
        # Half a 365-day year: 100*(1+r) + 100*sqrt(1+r) = 231.
        self.assertAlmostEqual(result["xirr_pct"], 21, places=6)
        self.assertEqual(result["profit_amount"], 31)

    def test_disposed_holding_uses_sale_net_of_costs(self):
        portfolio = _portfolio(
            _activity(),
            _activity(
                "sell",
                120,
                id="sell",
                when="2026-01-01",
                quantity=1,
                fees={"amount": 2, "currency": "BRL"},
                withholding_tax={"amount": 3, "currency": "BRL"},
            ),
        )
        portfolio["holdings"][0].update(
            quantity=0, market_value={"amount": 0, "currency": "BRL"}
        )
        result = self.compute(portfolio)
        self.assertEqual(result["observed_sell_inflows"], 115)
        self.assertEqual(result["profit_amount"], 15)
        self.assertAlmostEqual(result["xirr_pct"], 15, places=7)

    def test_amortization_is_cash_received_without_reducing_units(self):
        result = self.compute(
            _portfolio(
                _activity(), _activity("amortization", 5, id="amort", when="2026-01-01")
            )
        )
        self.assertEqual(result["profit_amount"], 15)
        self.assertEqual(result["observed_distributions"], 5)

    def test_signed_split_quantity_delta_changes_units_without_cashflow(self):
        portfolio = _portfolio(
            _activity(),
            _activity("split", 0, id="split", when="2025-06-01", quantity=1),
        )
        portfolio["holdings"][0]["quantity"] = 2
        result = self.compute(portfolio)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["cashflows"]), 2)
        self.assertAlmostEqual(result["xirr_pct"], 10, places=7)

    def test_cross_holding_merger_requires_predecessor_cash_lineage(self):
        portfolio = _portfolio(
            _activity(),
            _activity(
                "merger",
                0,
                id="merger",
                when="2025-06-01",
                holding_id="h-other",
                corporate_action={
                    "kind": "merger",
                    "legs": [
                        {"holding_id": "h-other", "quantity_delta": -2},
                        {"holding_id": "h-fii", "quantity_delta": 1},
                    ],
                },
            ),
        )
        portfolio["holdings"][0]["quantity"] = 2
        result = self.compute(portfolio)
        self.assert_incomplete(result)
        self.assertEqual(result["observed_net_cashflow"], -100)
        self.assertTrue(any("lineage" in warning for warning in result["warnings"]))

    def test_cross_holding_other_conversions_require_cash_lineage(self):
        for kind in ("subscription_conversion", "rights_issue", "ticker_change"):
            with self.subTest(kind=kind):
                portfolio = _portfolio(
                    _activity(),
                    _activity(
                        "other",
                        0,
                        id="conversion",
                        when="2025-06-01",
                        corporate_action={
                            "kind": kind,
                            "legs": [
                                {"holding_id": "h-other", "quantity_delta": -2},
                                {"holding_id": "h-fii", "quantity_delta": 1},
                            ],
                        },
                    ),
                )
                portfolio["holdings"][0]["quantity"] = 2
                result = self.compute(portfolio)
                self.assert_incomplete(result)
                self.assertEqual(result["observed_buy_outflows"], 100)

    def test_missing_split_units_prevent_quantity_reconciliation(self):
        portfolio = _portfolio(
            _activity(), _activity("split", 0, id="split", when="2025-06-01")
        )
        self.assert_incomplete(self.compute(portfolio))

    def test_missing_partial_and_gapped_history_never_publish_full_return(self):
        for history in (
            None,
            {"status": "partial"},
            {"status": "unknown"},
            {"status": "complete", "from": "2025-01-02", "through": "2026-01-01"},
            {"status": "complete", "from": "2025-01-01", "through": "2025-12-31"},
            {
                "status": "complete",
                "from": "2025-01-01",
                "through": "2026-01-01",
                "missing_periods": [
                    {"from": "2025-02-01", "through": "2025-03-01", "kind": "buys"}
                ],
            },
        ):
            with self.subTest(history=history):
                portfolio = _portfolio()
                portfolio["holdings"][0]["extensions"] = {
                    "rikdom_instrument_history": history
                }
                result = self.compute(portfolio)
                self.assert_incomplete(result)
                self.assertEqual(result["observed_buy_outflows"], 100)

    def test_mismatched_currency_is_not_added_or_converted(self):
        portfolio = _portfolio(
            _activity(),
            _activity(
                "dividend",
                5,
                id="usd",
                when="2026-01-01",
                money={"amount": 5, "currency": "USD"},
                metadata={"fx_rate_to_base": 5},
            ),
        )
        result = self.compute(portfolio)
        self.assert_incomplete(result)
        self.assertEqual(result["observed_distributions"], 0)
        self.assertEqual(result["observed_net_cashflow"], -100)

    def test_pending_cancelled_irrelevant_and_exact_duplicates_are_excluded(self):
        buy = _activity()
        portfolio = _portfolio(
            buy,
            copy.deepcopy(buy),
            _activity("sell", 50, id="cancel", status="cancelled"),
            _activity("buy", 500, id="pending", status="pending"),
            _activity("dividend", 500, id="other-holding", holding_id="h-other"),
            _activity(
                "dividend",
                500,
                id="other-ticker",
                holding_id=None,
                instrument={"ticker": "OTHER"},
            ),
        )
        result = self.compute(portfolio)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["observed_buy_outflows"], 100)
        self.assertEqual(result["observed_distributions"], 0)

    def test_settlement_date_takes_precedence_and_cashflows_sort_chronologically(self):
        portfolio = _portfolio(
            _activity("dividend", 5, id="div", when="2026-01-01"),
            _activity(when="2024-12-30", settled_at="2025-01-01"),
        )
        result = self.compute(portfolio)
        self.assertAlmostEqual(result["xirr_pct"], 15, places=7)
        self.assertEqual(result["period_start"][:10], "2025-01-01")
        self.assertEqual(result["cashflows"][0]["activity_id"], "buy-1")

    def test_stale_or_future_default_valuation_is_suppressed(self):
        for until in ("2026-02-01", "2025-12-01"):
            with self.subTest(until=until):
                result = self.compute(_portfolio(), until=until)
                self.assert_incomplete(result)
                self.assertIsNone(result["terminal_value"])

    def test_explicit_terminal_value_requires_an_explicit_valid_date(self):
        for kwargs in (
            {"terminal_value": 115},
            {"terminal_value": -1, "until": "2026-01-01"},
            {"terminal_value": float("nan"), "until": "2026-01-01"},
            {"terminal_value": float("inf"), "until": "2026-01-01"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.compute(_portfolio(), **kwargs)
        result = self.compute(_portfolio(), terminal_value=115, until="2026-01-01")
        self.assertEqual(result["valuation_basis"], "explicit_terminal_value")
        self.assertAlmostEqual(result["xirr_pct"], 15, places=7)

    def test_terminal_override_allows_later_date_when_history_covers_it(self):
        portfolio = _portfolio()
        portfolio["holdings"][0]["extensions"]["rikdom_instrument_history"][
            "through"
        ] = "2027-01-01"
        result = self.compute(portfolio, until="2027-01-01", terminal_value=121)
        self.assertEqual(result["status"], "complete")
        self.assertAlmostEqual(result["xirr_pct"], 10, places=7)

    def test_quantity_mismatch_blocks_since_purchase_return(self):
        portfolio = _portfolio()
        portfolio["holdings"][0]["quantity"] = 50
        self.assert_incomplete(self.compute(portfolio))

    def test_tax_lots_cannot_substitute_for_acquisition_cashflows(self):
        portfolio = _portfolio(_activity("dividend", 5, id="div", when="2026-01-01"))
        portfolio["tax_lots"] = [
            {
                "holding_id": "h-fii",
                "acquired_at": "2025-01-01",
                "cost_basis": {"amount": 100, "currency": "BRL"},
            }
        ]
        result = self.compute(portfolio)
        self.assert_incomplete(result)
        self.assertEqual(result["observed_buy_outflows"], 0)
        self.assertIsNone(result["period_start"])

    def test_malformed_matched_date_amount_and_costs_block_full_metrics(self):
        for override in (
            {"effective_at": "garbage"},
            {"settled_at": "garbage"},
            {"money": {"amount": float("nan"), "currency": "BRL"}},
            {"money": {"amount": True, "currency": "BRL"}},
            {"money": {"amount": 5, "currency": ""}},
            {"fees": {"amount": 1, "currency": "USD"}},
            {"withholding_tax": {"amount": -1, "currency": "BRL"}},
        ):
            with self.subTest(override=override):
                portfolio = _portfolio(
                    _activity(),
                    _activity("dividend", 5, id="bad", when="2026-01-01", **override),
                )
                self.assert_incomplete(self.compute(portfolio))

    def test_unhandled_other_and_asset_transfers_block_complete_history(self):
        for kind in ("other", "transfer_in", "transfer_out"):
            with self.subTest(kind=kind):
                self.assert_incomplete(
                    self.compute(
                        _portfolio(_activity(), _activity(kind, 0, id=kind, quantity=1))
                    )
                )

    def test_unambiguous_ticker_fallback_and_explicit_alias_match(self):
        portfolio = _portfolio(_activity(holding_id=None))
        self.assertEqual(self.compute(portfolio)["status"], "complete")
        portfolio["holdings"][0]["metadata"] = {"instrument_aliases": ["OLD11"]}
        portfolio["activities"][0]["instrument"] = {"ticker": "OLD11"}
        self.assertEqual(self.compute(portfolio)["status"], "complete")

    def test_ambiguous_ticker_fallback_blocks_history_but_does_not_count_cash(self):
        portfolio = _portfolio(_activity(holding_id=None))
        portfolio["holdings"].append(
            {"id": "h-other", "identifiers": {"ticker": "FII11"}}
        )
        result = self.compute(portfolio)
        self.assert_incomplete(result)
        self.assertEqual(result["observed_buy_outflows"], 0)

    def test_conflicting_duplicate_ids_never_manufacture_cash(self):
        result = self.compute(_portfolio(_activity(), _activity(amount=1000)))
        self.assert_incomplete(result)
        self.assertEqual(result["observed_buy_outflows"], 100)

    def test_same_import_idempotency_key_does_not_duplicate_an_acquisition(self):
        portfolio = _portfolio(
            _activity(idempotency_key="broker-row-1"),
            _activity(id="imported-twice", idempotency_key="broker-row-1"),
        )
        result = self.compute(portfolio)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["observed_buy_outflows"], 100)

    def test_explicit_terminal_value_can_replace_missing_current_market_value(self):
        portfolio = _portfolio()
        portfolio["holdings"][0].pop("market_value")
        result = self.compute(portfolio, terminal_value=115, terminal_at="2026-01-01")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["currency"], "BRL")
        self.assertAlmostEqual(result["xirr_pct"], 15, places=7)

    def test_zero_transfer_without_asset_or_cash_movement_is_harmless(self):
        result = self.compute(
            _portfolio(_activity(), _activity("transfer_in", 0, id="zero"))
        )
        self.assertEqual(result["status"], "complete")

    def test_corporate_action_cash_component_is_not_silently_lost(self):
        result = self.compute(
            _portfolio(_activity(), _activity("split", 5, id="split", quantity=0))
        )
        self.assert_incomplete(result)
        self.assertEqual(result["observed_distributions"], 0)

    def test_cash_received_before_first_acquisition_signals_missing_inception(self):
        portfolio = _portfolio(
            _activity(), _activity("dividend", 5, id="early", when="2024-12-31")
        )
        portfolio["holdings"][0]["extensions"]["rikdom_instrument_history"]["from"] = (
            "2024-01-01"
        )
        self.assert_incomplete(self.compute(portfolio))

    def test_timestamp_valuation_excludes_cash_that_settles_after_it(self):
        portfolio = _portfolio(
            _activity(),
            _activity("dividend", 5, id="late", when="2026-01-01T15:00:00Z"),
        )
        portfolio["holdings"][0]["as_of"] = "2026-01-01T12:00:00Z"
        result = self.compute(portfolio, until="2026-01-01")
        self.assertEqual(result["observed_distributions"], 0)

    def test_invalid_explicit_terminal_date_and_mismatched_until_raise(self):
        for kwargs in (
            {"terminal_value": 100, "terminal_at": "garbage"},
            {"terminal_value": 100, "terminal_at": "2026-01-02", "until": "2026-01-01"},
            {"terminal_at": "2026-01-01"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.compute(_portfolio(), **kwargs)

    def test_zero_duration_does_not_publish_an_annual_return(self):
        portfolio = _portfolio(_activity(when="2026-01-01"))
        portfolio["holdings"][0]["market_value"]["amount"] = 100
        result = self.compute(portfolio)
        self.assertEqual(result["profit_amount"], 0)
        self.assertIsNone(result["xirr_pct"])

    def test_malformed_corporate_action_cannot_crash_or_assert_completeness(self):
        portfolio = _portfolio(
            _activity(),
            _activity(
                "split",
                0,
                id="split",
                quantity=0,
                corporate_action={"kind": "split", "legs": None},
            ),
        )
        self.assert_incomplete(self.compute(portfolio))

    def test_future_override_still_checks_known_current_quantity(self):
        portfolio = _portfolio()
        portfolio["holdings"][0]["quantity"] = 50
        portfolio["holdings"][0]["extensions"]["rikdom_instrument_history"][
            "through"
        ] = "2027-01-01"
        self.assert_incomplete(
            self.compute(portfolio, terminal_value=121, until="2027-01-01")
        )

    def test_selling_more_units_than_acquired_blocks_missing_history(self):
        portfolio = _portfolio(
            _activity(),
            _activity("sell", 200, id="sell", when="2025-03-01", quantity=2),
            _activity(amount=200, id="buy-2", when="2025-06-01", quantity=2),
        )
        self.assert_incomplete(self.compute(portfolio))

    def test_typed_other_corporate_action_reconstructs_non_cash_units(self):
        portfolio = _portfolio(
            _activity(),
            _activity(
                "other",
                0,
                id="subscription",
                when="2025-06-01",
                corporate_action={
                    "kind": "subscription_conversion",
                    "legs": [
                        {"holding_id": "h-fii", "quantity_delta": 1},
                    ],
                },
            ),
        )
        portfolio["holdings"][0]["quantity"] = 2
        result = self.compute(portfolio)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["observed_net_cashflow"], -100)

    def test_same_day_explicit_override_still_reconciles_known_units(self):
        portfolio = _portfolio()
        portfolio["holdings"][0].update(as_of="2026-01-01T12:00:00Z", quantity=50)
        self.assert_incomplete(
            self.compute(portfolio, terminal_value=110, until="2026-01-01")
        )

    def test_future_ambiguous_activity_is_outside_the_return_period(self):
        portfolio = _portfolio(
            _activity(),
            _activity("dividend", 5, id="future", when="2027-01-01", holding_id=None),
        )
        portfolio["holdings"].append(
            {"id": "h-other", "identifiers": {"ticker": "FII11"}}
        )
        self.assertEqual(self.compute(portfolio)["status"], "complete")

    def test_zero_cash_acquisition_does_not_establish_invested_capital(self):
        self.assert_incomplete(self.compute(_portfolio(_activity(amount=0))))


if __name__ == "__main__":
    unittest.main()
