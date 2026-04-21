from __future__ import annotations

import unittest

from rikdom.aggregate import aggregate_portfolio
from rikdom.storage import load_json


class AggregateTests(unittest.TestCase):
    def test_aggregate_total(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        result = aggregate_portfolio(portfolio)
        self.assertEqual(result.base_currency, "BRL")
        self.assertAlmostEqual(result.total_value_base, 165830.0)
        self.assertIn("stocks", result.by_asset_class)

    def test_aggregate_uses_fx_rates_argument_without_manual_metadata(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-us",
                    "asset_type_id": "stock",
                    "label": "US Asset",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                }
            ],
        }
        result = aggregate_portfolio(portfolio, fx_rates_to_base={"USD": 5.0})
        self.assertAlmostEqual(result.total_value_base, 500.0)
        self.assertEqual(result.by_asset_class.get("stocks"), 500.0)
        self.assertEqual(result.warnings, [])

    def test_aggregate_metadata_fx_rate_to_base_is_compat_fallback(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-us",
                    "asset_type_id": "stock",
                    "label": "US Asset",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                    "metadata": {"fx_rate_to_base": 5.1},
                }
            ],
        }
        result = aggregate_portfolio(portfolio)
        self.assertAlmostEqual(result.total_value_base, 510.0)
        self.assertTrue(any("compatibility fallback" in warning for warning in result.warnings))

    def test_strict_quality_turns_missing_fx_warning_into_error(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-us",
                    "asset_type_id": "stock",
                    "label": "US Asset",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                }
            ],
        }
        result = aggregate_portfolio(portfolio, strict=True)
        self.assertEqual(result.total_value_base, 0.0)
        self.assertTrue(any("missing base conversion" in err for err in result.errors))

    def test_quantity_consistency_warning_for_holding_vs_activity_ledger(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-petr4",
                    "asset_type_id": "stock",
                    "label": "PETR4",
                    "identifiers": {"ticker": "PETR4"},
                    "quantity": 10,
                    "market_value": {"amount": 1000.0, "currency": "BRL"},
                }
            ],
            "activities": [
                {
                    "id": "act-buy-petr4",
                    "event_type": "buy",
                    "status": "posted",
                    "effective_at": "2026-04-01T00:00:00Z",
                    "asset_type_id": "stock",
                    "instrument": {"ticker": "PETR4"},
                    "quantity": 6,
                },
                {
                    "id": "act-sell-petr4",
                    "event_type": "sell",
                    "status": "posted",
                    "effective_at": "2026-04-02T00:00:00Z",
                    "asset_type_id": "stock",
                    "instrument": {"ticker": "PETR4"},
                    "quantity": 1,
                },
            ],
        }
        result = aggregate_portfolio(portfolio)
        self.assertTrue(any("Quantity drift for holding" in warning for warning in result.warnings))

    def test_cash_drift_warning_for_cash_equivalent_ledger_gap(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "cash_equivalent", "asset_class": "cash_equivalents"}],
            "holdings": [
                {
                    "id": "h-cash",
                    "asset_type_id": "cash_equivalent",
                    "label": "Cash",
                    "market_value": {"amount": 1000.0, "currency": "BRL"},
                }
            ],
            "activities": [
                {
                    "id": "act-cash-in",
                    "event_type": "transfer_in",
                    "status": "posted",
                    "effective_at": "2026-04-01T00:00:00Z",
                    "asset_type_id": "cash_equivalent",
                    "money": {"amount": 900.0, "currency": "BRL"},
                }
            ],
        }
        result = aggregate_portfolio(portfolio)
        self.assertTrue(any("Cash drift detected" in warning for warning in result.warnings))

    def test_quantity_matching_prefers_high_confidence_identifier_over_wallet(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-petr4",
                    "asset_type_id": "stock",
                    "label": "PETR4",
                    "identifiers": {"ticker": "PETR4", "wallet": "wallet-1"},
                    "quantity": 10,
                    "market_value": {"amount": 1000.0, "currency": "BRL"},
                }
            ],
            "activities": [
                {
                    "id": "act-buy-petr4",
                    "event_type": "buy",
                    "status": "posted",
                    "effective_at": "2026-04-01T00:00:00Z",
                    "asset_type_id": "stock",
                    "instrument": {"ticker": "PETR4", "wallet": "wallet-1"},
                    "quantity": 10,
                },
                {
                    "id": "act-buy-vale3",
                    "event_type": "buy",
                    "status": "posted",
                    "effective_at": "2026-04-02T00:00:00Z",
                    "asset_type_id": "stock",
                    "instrument": {"ticker": "VALE3", "wallet": "wallet-1"},
                    "quantity": 4,
                },
            ],
        }
        result = aggregate_portfolio(portfolio)
        self.assertFalse(
            any("Quantity drift for holding 'h-petr4'" in warning for warning in result.warnings)
        )

    def test_quantity_wallet_fallback_skips_activities_with_instrument_identifier(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-wallet-only",
                    "asset_type_id": "stock",
                    "label": "Wallet Position",
                    "identifiers": {"wallet": "wallet-1"},
                    "quantity": 5,
                    "market_value": {"amount": 500.0, "currency": "BRL"},
                }
            ],
            "activities": [
                {
                    "id": "act-wallet-only",
                    "event_type": "buy",
                    "status": "posted",
                    "effective_at": "2026-04-01T00:00:00Z",
                    "asset_type_id": "stock",
                    "instrument": {"wallet": "wallet-1"},
                    "quantity": 5,
                },
                {
                    "id": "act-wallet-with-ticker",
                    "event_type": "buy",
                    "status": "posted",
                    "effective_at": "2026-04-02T00:00:00Z",
                    "asset_type_id": "stock",
                    "instrument": {"wallet": "wallet-1", "ticker": "VALE3"},
                    "quantity": 3,
                },
            ],
        }
        result = aggregate_portfolio(portfolio)
        self.assertFalse(
            any("Quantity drift for holding 'h-wallet-only'" in warning for warning in result.warnings)
        )

    def test_invalid_market_value_reports_warning_or_error_by_strict_mode(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-invalid",
                    "asset_type_id": "stock",
                    "label": "Broken",
                    "market_value": {"amount": "bad", "currency": "BRL"},
                }
            ],
        }
        non_strict = aggregate_portfolio(portfolio, strict=False)
        self.assertTrue(
            any("Holding 'h-invalid' has malformed market_value" in warning for warning in non_strict.warnings)
        )
        self.assertEqual(non_strict.errors, [])

        strict = aggregate_portfolio(portfolio, strict=True)
        self.assertTrue(
            any("Holding 'h-invalid' has malformed market_value" in err for err in strict.errors)
        )

    def test_invalid_cash_money_and_fees_report_warning_or_error_by_strict_mode(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "cash_equivalent", "asset_class": "cash_equivalents"}],
            "holdings": [
                {
                    "id": "h-cash",
                    "asset_type_id": "cash_equivalent",
                    "label": "Cash",
                    "market_value": {"amount": 100.0, "currency": "BRL"},
                }
            ],
            "activities": [
                {
                    "id": "act-invalid-money",
                    "event_type": "transfer_in",
                    "status": "posted",
                    "effective_at": "2026-04-01T00:00:00Z",
                    "asset_type_id": "cash_equivalent",
                    "money": "bad",
                },
                {
                    "id": "act-invalid-fees",
                    "event_type": "transfer_out",
                    "status": "posted",
                    "effective_at": "2026-04-02T00:00:00Z",
                    "asset_type_id": "cash_equivalent",
                    "money": {"amount": 20.0, "currency": "BRL"},
                    "fees": {"amount": "bad", "currency": "BRL"},
                },
            ],
        }
        non_strict = aggregate_portfolio(portfolio, strict=False)
        self.assertTrue(
            any("Cash activity 'act-invalid-money' has non-object money" in warning for warning in non_strict.warnings)
        )
        self.assertTrue(
            any("Cash activity 'act-invalid-fees' has malformed fees" in warning for warning in non_strict.warnings)
        )

        strict = aggregate_portfolio(portfolio, strict=True)
        self.assertTrue(
            any("Cash activity 'act-invalid-money' has non-object money" in err for err in strict.errors)
        )
        self.assertTrue(
            any("Cash activity 'act-invalid-fees' has malformed fees" in err for err in strict.errors)
        )

    def test_base_currency_defaults_to_usd_for_empty_or_non_string_values(self) -> None:
        for raw_base_currency in ("", 123):
            with self.subTest(raw_base_currency=raw_base_currency):
                portfolio = {
                    "settings": {"base_currency": raw_base_currency},
                    "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
                    "holdings": [
                        {
                            "id": "h-usd",
                            "asset_type_id": "stock",
                            "label": "USD Asset",
                            "market_value": {"amount": 100.0, "currency": "USD"},
                        }
                    ],
                }
                result = aggregate_portfolio(portfolio)
                self.assertEqual(result.base_currency, "USD")
                self.assertAlmostEqual(result.total_value_base, 100.0)


if __name__ == "__main__":
    unittest.main()
