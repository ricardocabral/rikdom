from __future__ import annotations

import unittest

from rikdom.storage import load_json
from rikdom.validate import validate_portfolio


def _portfolio_with_activities(activities: list[dict]) -> dict:
    return {
        "schema_version": "1.4.0",
        "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
        "profile": {
            "portfolio_id": "p",
            "owner_kind": "person",
            "display_name": "P",
        },
        "settings": {"base_currency": "BRL"},
        "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
        "holdings": [
            {
                "id": "h1",
                "asset_type_id": "stock",
                "label": "A",
                "market_value": {"amount": 100.0, "currency": "BRL"},
            },
        ],
        "tax_lots": [
            {
                "id": "lot-1",
                "holding_id": "h1",
                "acquired_at": "2026-01-02T00:00:00Z",
                "quantity": 5,
                "cost_basis": {"amount": 90, "currency": "BRL"},
            }
        ],
        "activities": activities,
    }


def _activity(**kwargs) -> dict:
    base = {
        "id": "act-1",
        "event_type": "buy",
        "status": "posted",
        "effective_at": "2026-04-19T15:00:00Z",
    }
    base.update(kwargs)
    return base


class EventTypeEnumTests(unittest.TestCase):
    def test_new_event_types_accepted(self) -> None:
        for et in (
            "merger",
            "contribution",
            "withdrawal",
            "tax_withheld",
            "fx_conversion",
        ):
            with self.subTest(event_type=et):
                acts = [_activity(id=f"a-{et}", event_type=et)]
                # fx_conversion needs counter_money — give it for this enum check
                if et == "fx_conversion":
                    acts[0]["counter_money"] = {"amount": 1, "currency": "USD"}
                    acts[0]["money"] = {"amount": 5, "currency": "BRL"}
                portfolio = _portfolio_with_activities(acts)
                errors = validate_portfolio(portfolio)
                self.assertEqual(
                    [e for e in errors if "event_type" in e], [], errors
                )

    def test_unknown_event_type_rejected(self) -> None:
        portfolio = _portfolio_with_activities(
            [_activity(event_type="rocketship")]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(
            any("event_type 'rocketship'" in e for e in errors), errors
        )


class CrossReferenceTests(unittest.TestCase):
    def test_holding_id_must_resolve(self) -> None:
        portfolio = _portfolio_with_activities(
            [_activity(holding_id="h-ghost")]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(any("h-ghost" in e for e in errors), errors)

    def test_tax_lot_ids_must_resolve(self) -> None:
        portfolio = _portfolio_with_activities(
            [
                _activity(
                    event_type="sell",
                    tax_lot_ids=["lot-1", "lot-ghost"],
                    quantity=2,
                    money={"amount": 100, "currency": "BRL"},
                )
            ]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(any("lot-ghost" in e for e in errors), errors)
        # lot-1 should not produce an error
        self.assertFalse(any("'lot-1'" in e for e in errors), errors)

    def test_account_id_pattern_validated(self) -> None:
        portfolio = _portfolio_with_activities(
            [_activity(account_id="UPPER-CASE")]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(
            any(
                "activities[0].account_id" in e and "pattern" in e
                for e in errors
            ),
            errors,
        )


class FxConversionSemanticsTests(unittest.TestCase):
    def test_fx_conversion_requires_counter_money(self) -> None:
        portfolio = _portfolio_with_activities(
            [
                _activity(
                    id="fx-1",
                    event_type="fx_conversion",
                    money={"amount": 100, "currency": "BRL"},
                )
            ]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(
            any("counter_money is required" in e for e in errors), errors
        )

    def test_fx_rate_must_be_positive(self) -> None:
        portfolio = _portfolio_with_activities(
            [
                _activity(
                    id="fx-1",
                    event_type="fx_conversion",
                    money={"amount": 100, "currency": "BRL"},
                    counter_money={"amount": 20, "currency": "USD"},
                    fx_rate=-1,
                )
            ]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(
            any("fx_rate must be a positive number" in e for e in errors),
            errors,
        )

    def test_well_formed_fx_conversion_passes(self) -> None:
        portfolio = _portfolio_with_activities(
            [
                _activity(
                    id="fx-1",
                    event_type="fx_conversion",
                    money={"amount": 100, "currency": "BRL"},
                    counter_money={"amount": 20, "currency": "USD"},
                    fx_rate=5.0,
                )
            ]
        )
        errors = validate_portfolio(portfolio)
        self.assertEqual(errors, [])


class MoneyShapeChecksTests(unittest.TestCase):
    def test_withholding_tax_must_be_money(self) -> None:
        portfolio = _portfolio_with_activities(
            [_activity(event_type="dividend", withholding_tax=10)]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(
            any("withholding_tax" in e for e in errors), errors
        )

    def test_realized_gain_must_be_money(self) -> None:
        portfolio = _portfolio_with_activities(
            [_activity(event_type="sell", realized_gain="positive")]
        )
        errors = validate_portfolio(portfolio)
        self.assertTrue(any("realized_gain" in e for e in errors), errors)


class SamplePortfolioTests(unittest.TestCase):
    def test_data_sample_validates_with_new_activities(self) -> None:
        portfolio = load_json("data-sample/portfolio.json")
        # Sample is at older schema_version; the migration owns the bump.
        # Force-bump in-memory just for this validation pass.
        portfolio["schema_version"] = "1.4.0"
        errors = validate_portfolio(portfolio)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
