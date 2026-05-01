from __future__ import annotations

import unittest

from rikdom.fx import attach_fx_refs_to_holdings
from rikdom.validate import validate_fx_provenance, validate_portfolio


def _minimal_portfolio_v1_5_0(extra: dict | None = None) -> dict:
    portfolio = {
        "schema_version": "1.5.0",
        "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
        "profile": {
            "portfolio_id": "p1",
            "owner_kind": "person",
            "display_name": "Test",
        },
        "settings": {"base_currency": "BRL"},
        "asset_type_catalog": [
            {"id": "stock", "label": "Stock", "asset_class": "equities"},
        ],
        "holdings": [],
    }
    if extra:
        portfolio.update(extra)
    return portfolio


class ValidateFxProvenanceTests(unittest.TestCase):
    def test_warns_when_foreign_currency_money_lacks_fx_ref(self) -> None:
        portfolio = _minimal_portfolio_v1_5_0(
            {
                "holdings": [
                    {
                        "id": "h-aapl",
                        "asset_type_id": "stock",
                        "label": "AAPL",
                        "market_value": {"amount": 100, "currency": "USD"},
                    }
                ]
            }
        )
        warnings = validate_fx_provenance(portfolio)
        self.assertEqual(len(warnings), 1)
        self.assertIn("holdings[0].market_value", warnings[0])
        self.assertIn("USD", warnings[0])
        self.assertIn("BRL", warnings[0])

    def test_no_warning_when_currency_matches_base(self) -> None:
        portfolio = _minimal_portfolio_v1_5_0(
            {
                "holdings": [
                    {
                        "id": "h-brl",
                        "asset_type_id": "stock",
                        "label": "VALE3",
                        "market_value": {"amount": 100, "currency": "BRL"},
                    }
                ]
            }
        )
        self.assertEqual(validate_fx_provenance(portfolio), [])

    def test_no_warning_when_fx_ref_present(self) -> None:
        portfolio = _minimal_portfolio_v1_5_0(
            {
                "holdings": [
                    {
                        "id": "h-aapl",
                        "asset_type_id": "stock",
                        "label": "AAPL",
                        "market_value": {
                            "amount": 100,
                            "currency": "USD",
                            "fx_ref": {
                                "as_of_date": "2026-04-19",
                                "base_currency": "BRL",
                                "quote_currency": "USD",
                                "rate_to_base": 5.25,
                                "source": "history",
                            },
                        },
                    }
                ]
            }
        )
        self.assertEqual(validate_fx_provenance(portfolio), [])
        self.assertEqual(validate_portfolio(portfolio), [])

    def test_warns_when_fx_ref_base_does_not_match_settings(self) -> None:
        portfolio = _minimal_portfolio_v1_5_0(
            {
                "holdings": [
                    {
                        "id": "h-aapl",
                        "asset_type_id": "stock",
                        "label": "AAPL",
                        "market_value": {
                            "amount": 100,
                            "currency": "USD",
                            "fx_ref": {
                                "as_of_date": "2026-04-19",
                                "base_currency": "EUR",
                                "quote_currency": "USD",
                                "rate_to_base": 0.9,
                            },
                        },
                    }
                ]
            }
        )
        warnings = validate_fx_provenance(portfolio)
        self.assertTrue(any("does not match" in w for w in warnings))


class ValidatePortfolioFxRefSemanticTests(unittest.TestCase):
    def test_fx_ref_quote_currency_must_match_enclosing_money(self) -> None:
        portfolio = _minimal_portfolio_v1_5_0(
            {
                "holdings": [
                    {
                        "id": "h-aapl",
                        "asset_type_id": "stock",
                        "label": "AAPL",
                        "market_value": {
                            "amount": 100,
                            "currency": "USD",
                            "fx_ref": {
                                "as_of_date": "2026-04-19",
                                "base_currency": "BRL",
                                "quote_currency": "EUR",
                                "rate_to_base": 5.25,
                            },
                        },
                    }
                ]
            }
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(
            any("quote_currency" in e and "must equal" in e for e in errors), errors
        )

    def test_fx_ref_rate_must_be_positive(self) -> None:
        portfolio = _minimal_portfolio_v1_5_0(
            {
                "holdings": [
                    {
                        "id": "h-aapl",
                        "asset_type_id": "stock",
                        "label": "AAPL",
                        "market_value": {
                            "amount": 100,
                            "currency": "USD",
                            "fx_ref": {
                                "as_of_date": "2026-04-19",
                                "base_currency": "BRL",
                                "quote_currency": "USD",
                                "rate_to_base": 0,
                            },
                        },
                    }
                ]
            }
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(any("rate_to_base" in e for e in errors), errors)

    def test_fx_ref_as_of_date_must_be_iso(self) -> None:
        portfolio = _minimal_portfolio_v1_5_0(
            {
                "holdings": [
                    {
                        "id": "h-aapl",
                        "asset_type_id": "stock",
                        "label": "AAPL",
                        "market_value": {
                            "amount": 100,
                            "currency": "USD",
                            "fx_ref": {
                                "as_of_date": "04/19/2026",
                                "base_currency": "BRL",
                                "quote_currency": "USD",
                                "rate_to_base": 5.25,
                            },
                        },
                    }
                ]
            }
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(any("as_of_date" in e for e in errors), errors)


class AttachFxRefsTests(unittest.TestCase):
    def _fx_lock(self) -> dict:
        return {
            "base_currency": "BRL",
            "snapshot_timestamp": "2026-04-20T00:00:00Z",
            "rates_to_base": {"USD": 5.25, "EUR": 5.6},
            "rate_dates": {"USD": "2026-04-19", "EUR": "2026-04-19"},
            "sources": {"USD": "history", "EUR": "auto_ingest"},
        }

    def test_stamps_fx_ref_on_foreign_currency_holdings(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [
                {"id": "h-aapl", "market_value": {"amount": 100, "currency": "USD"}},
                {"id": "h-vale", "market_value": {"amount": 200, "currency": "BRL"}},
            ],
        }
        result = attach_fx_refs_to_holdings(portfolio, self._fx_lock())
        usd_mv = result["holdings"][0]["market_value"]
        self.assertEqual(
            usd_mv["fx_ref"],
            {
                "as_of_date": "2026-04-19",
                "base_currency": "BRL",
                "quote_currency": "USD",
                "rate_to_base": 5.25,
                "source": "history",
            },
        )
        # Base-currency money is left untouched.
        self.assertNotIn("fx_ref", result["holdings"][1]["market_value"])

    def test_does_not_overwrite_existing_fx_ref(self) -> None:
        existing = {
            "as_of_date": "2026-04-15",
            "base_currency": "BRL",
            "quote_currency": "USD",
            "rate_to_base": 5.10,
            "source": "manual",
        }
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [
                {
                    "id": "h-aapl",
                    "market_value": {
                        "amount": 100,
                        "currency": "USD",
                        "fx_ref": dict(existing),
                    },
                }
            ],
        }
        result = attach_fx_refs_to_holdings(portfolio, self._fx_lock())
        self.assertEqual(result["holdings"][0]["market_value"]["fx_ref"], existing)

    def test_does_not_mutate_input(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [
                {"id": "h-aapl", "market_value": {"amount": 100, "currency": "USD"}}
            ],
        }
        attach_fx_refs_to_holdings(portfolio, self._fx_lock())
        self.assertNotIn("fx_ref", portfolio["holdings"][0]["market_value"])

    def test_stamps_fx_ref_on_activity_money(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [],
            "activities": [
                {
                    "id": "a1",
                    "event_type": "dividend",
                    "status": "posted",
                    "effective_at": "2026-04-19T00:00:00Z",
                    "money": {"amount": 10, "currency": "USD"},
                }
            ],
        }
        result = attach_fx_refs_to_holdings(portfolio, self._fx_lock())
        self.assertEqual(
            result["activities"][0]["money"]["fx_ref"]["quote_currency"], "USD"
        )

    def test_skips_currencies_without_rate_in_lock(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "holdings": [
                {"id": "h-jpy", "market_value": {"amount": 1000, "currency": "JPY"}},
            ],
        }
        result = attach_fx_refs_to_holdings(portfolio, self._fx_lock())
        self.assertNotIn("fx_ref", result["holdings"][0]["market_value"])


if __name__ == "__main__":
    unittest.main()
