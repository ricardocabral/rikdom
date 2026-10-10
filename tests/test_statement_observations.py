from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from rikdom.validate import validate_portfolio
from rikdom.migrations import apply_migrations, plan_migrations


def money(amount):
    return {"amount": amount, "currency": "BRL"}


def portfolio():
    return {
        "schema_version": "1.6.0",
        "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
        "profile": {"portfolio_id": "p", "owner_kind": "person", "display_name": "P"},
        "settings": {"base_currency": "BRL"},
        "asset_type_catalog": [{"id": "fund", "label": "Fund", "asset_class": "funds"}],
        "holdings": [
            {
                "id": "h",
                "asset_type_id": "fund",
                "label": "Fund",
                "market_value": money(100),
            }
        ],
    }


def observation():
    return {
        "id": "s",
        "provider": "broker",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "source": {"path": "synthetic.pdf", "sha256": "a" * 64, "page_count": 2},
        "balances": [
            {
                "label": "Fund",
                "as_of": "2026-01-30",
                "gross_value": money(100),
                "net_value": money(95),
            }
        ],
        "sections": [
            {
                "name": "Positions",
                "page": 2,
                "text": "synthetic table",
                "rows": [{"broker_column": "retained"}],
            }
        ],
    }


class StatementObservationTests(unittest.TestCase):
    def schema_errors(self, payload, name="portfolio"):
        schema = json.loads(Path(f"schema/{name}.schema.json").read_text())
        return list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                payload
            )
        )

    def test_report_and_adjusted_cost_are_preserved_without_tax_lots(self):
        p = portfolio()
        p["statement_observations"] = [observation()]
        p["holdings"][0].update(
            {
                "valuation": {
                    "unit_price": money(10),
                    "net_value": money(95),
                    "tax_provisions": [{"tax_type": "IR", "money": money(5)}],
                    "price_as_of": "2026-01-30T00:00:00Z",
                },
                "acquisition_observations": [
                    {
                        "acquired_at": "2022-01-01T00:00:00Z",
                        "observed_at": "2026-01-30T00:00:00Z",
                        "quantity": 10,
                        "reported_purchase_value": money(60),
                        "cost_basis_kind": "broker_adjusted_purchase_value",
                    }
                ],
            }
        )
        self.assertEqual(self.schema_errors(p), [])
        self.assertEqual(validate_portfolio(p), [])
        self.assertNotIn("tax_lots", p)

    def test_statement_only_plugin_output(self):
        p = {
            "provider": "broker",
            "generated_at": "2026-02-01T00:00:00Z",
            "statement_observations": [observation()],
        }
        self.assertEqual(self.schema_errors(p, "plugin-statement"), [])

    def test_invalid_observation_contracts_are_rejected(self):
        for field, value in [
            ("period_end", "2026-02-30"),
            ("source", {"path": "x", "sha256": "bad", "page_count": 0}),
            ("sections", [{"name": "X", "page": 0, "text": "x"}]),
        ]:
            with self.subTest(field=field):
                p = portfolio()
                p["statement_observations"] = [observation()]
                p["statement_observations"][0][field] = value
                self.assertTrue(self.schema_errors(p))
                self.assertTrue(validate_portfolio(p))

    def test_invalid_valuation_and_basis_kind_are_rejected(self):
        for field, value in [
            ("valuation", {"net_value": money("bad")}),
            (
                "acquisition_observations",
                [
                    {
                        "acquired_at": "bad",
                        "observed_at": "2026-01-01T00:00:00Z",
                        "quantity": 1,
                        "cost_basis_kind": "inferred",
                    }
                ],
            ),
        ]:
            p = portfolio()
            p["holdings"][0][field] = value
            self.assertTrue(self.schema_errors(p))
            self.assertTrue(validate_portfolio(p))

    def test_coupon_index_multiplier_and_rate_scope_are_typed(self):
        p = portfolio()
        p["holdings"][0]["fixed_income_profile"] = {
            "coupon": {
                "indexer_multiplier_pct": "102.25",
                "reported_rate": "102.25% CDI",
                "rate_scope": "inferred",
            }
        }
        self.assertTrue(self.schema_errors(p))
        self.assertTrue(validate_portfolio(p))
        p["holdings"][0]["fixed_income_profile"]["coupon"].update(
            indexer_multiplier_pct=102.25, rate_scope="weighted_average"
        )
        self.assertEqual(self.schema_errors(p), [])
        self.assertEqual(validate_portfolio(p), [])

    def test_migration_preserves_data_without_inference(self):
        p = portfolio()
        p["extensions"] = {"custom": {"value": True}}
        expected = copy.deepcopy(p)
        expected["schema_version"] = "1.7.0"
        actual, _ = apply_migrations(p, plan_migrations((1, 6, 0), (1, 7, 0)))
        self.assertEqual(actual, expected)
        self.assertEqual(p["schema_version"], "1.6.0")
