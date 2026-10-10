from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from rikdom.validate import validate_portfolio
from rikdom.migrations import apply_migrations, plan_migrations


def portfolio():
    return {
        "schema_version": "1.6.0",
        "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
        "profile": {"portfolio_id": "p", "owner_kind": "person", "display_name": "P"},
        "settings": {"base_currency": "BRL"},
        "asset_type_catalog": [
            {"id": "fii", "label": "FII", "asset_class": "real_estate"}
        ],
        "holdings": [
            {
                "id": "old",
                "asset_type_id": "fii",
                "label": "Old",
                "market_value": {"amount": 0, "currency": "BRL"},
            },
            {
                "id": "new",
                "asset_type_id": "fii",
                "label": "New",
                "market_value": {"amount": 100, "currency": "BRL"},
            },
        ],
        "tax_lots": [
            {
                "id": "lot",
                "holding_id": "old",
                "acquired_at": "2025-01-01T00:00:00Z",
                "quantity": 10,
                "cost_basis": {"amount": 90, "currency": "BRL"},
            }
        ],
        "activities": [
            {
                "id": "a",
                "event_type": "amortization",
                "status": "posted",
                "effective_at": "2026-01-01T00:00:00Z",
                "trade_at": "2025-12-30T00:00:00Z",
                "settled_at": "2026-01-02T00:00:00Z",
                "holding_id": "old",
                "money": {"amount": 10, "currency": "BRL"},
                "cost_basis_adjustment": {"amount": -10, "currency": "BRL"},
            }
        ],
    }


class HistorySchemaTests(unittest.TestCase):
    def schema_errors(self, payload, name="portfolio"):
        schema = json.loads(Path(f"schema/{name}.schema.json").read_text())
        return list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                payload
            )
        )

    def test_dated_amortization_and_merger_preserve_asserted_basis(self):
        p = portfolio()
        p["holdings"][0]["extensions"] = {
            "custom": {"anything": True},
            "rikdom_instrument_history": {
                "status": "complete",
                "from": "2025-01-01",
                "through": "2026-01-02",
                "notes": ["broker verified"],
            },
        }
        p["activities"].append(
            {
                "id": "m",
                "event_type": "merger",
                "status": "posted",
                "effective_at": "2026-01-03T00:00:00Z",
                "corporate_action": {
                    "kind": "merger",
                    "exchange_ratio": 0.5,
                    "legs": [
                        {
                            "holding_id": "old",
                            "quantity_delta": -10,
                            "cost_basis_delta": {"amount": -80, "currency": "BRL"},
                            "tax_lot_ids": ["lot"],
                        },
                        {
                            "holding_id": "new",
                            "quantity_delta": 5,
                            "cost_basis_delta": {"amount": 80, "currency": "BRL"},
                        },
                    ],
                },
            }
        )
        self.assertEqual(self.schema_errors(p), [])
        self.assertEqual(validate_portfolio(p), [])

    def test_invalid_new_fields_rejected_by_both_validators(self):
        for field, value in [
            ("trade_at", "bad"),
            ("settled_at", "2026-02-30T00:00:00Z"),
            ("cost_basis_adjustment", {"amount": "unknown", "currency": "BRL"}),
            ("corporate_action", {"kind": "merger", "exchange_ratio": 0, "legs": []}),
        ]:
            with self.subTest(field=field):
                p = portfolio()
                p["activities"][0][field] = value
                self.assertTrue(self.schema_errors(p))
                self.assertTrue(any(field in e for e in validate_portfolio(p)))

    def test_complete_history_requires_dates_and_rejects_invalid_period(self):
        for history in [
            {"status": "complete"},
            {
                "status": "partial",
                "missing_periods": [
                    {"from": "2026-02-30", "through": "2026-03-01", "kind": "all"}
                ],
            },
        ]:
            p = portfolio()
            p["holdings"][0]["extensions"] = {"rikdom_instrument_history": history}
            self.assertTrue(self.schema_errors(p))
            self.assertTrue(
                any("rikdom_instrument_history" in e for e in validate_portfolio(p))
            )

    def test_corporate_action_references_must_resolve_even_with_empty_ledgers(self):
        p = portfolio()
        p["tax_lots"] = []
        p["activities"][0]["corporate_action"] = {
            "kind": "merger",
            "legs": [
                {
                    "holding_id": "missing",
                    "quantity_delta": 1,
                    "tax_lot_ids": ["missing-lot"],
                }
            ],
        }
        errors = validate_portfolio(p)
        self.assertTrue(any("holding_id" in e and "missing" in e for e in errors))
        self.assertTrue(any("tax_lot_ids" in e and "missing-lot" in e for e in errors))

    def test_statement_accepts_core_events_and_tax_lot_only_import(self):
        p = portfolio()
        for event in [
            "amortization",
            "merger",
            "tax_withheld",
            "contribution",
            "withdrawal",
            "fx_conversion",
        ]:
            a = copy.deepcopy(p["activities"][0])
            a["event_type"] = event
            statement = {
                "provider": "broker",
                "generated_at": "2026-01-01T00:00:00Z",
                "activities": [a],
            }
            self.assertEqual(self.schema_errors(statement, "plugin-statement"), [])
        self.assertEqual(
            self.schema_errors(
                {
                    "provider": "broker",
                    "generated_at": "2026-01-01T00:00:00Z",
                    "tax_lots": p["tax_lots"],
                },
                "plugin-statement",
            ),
            [],
        )

    def test_additive_migration_does_not_invent_history_or_basis(self):
        p = portfolio()
        p["schema_version"] = "1.5.0"
        before = copy.deepcopy(p)
        result, applied = apply_migrations(p, plan_migrations((1, 5, 0), (1, 6, 0)))
        before["schema_version"] = "1.6.0"
        self.assertEqual(result, before)
        self.assertEqual(p["schema_version"], "1.5.0")
        self.assertEqual(len(applied), 1)

    def test_real_br_fii_catalog_patterns_and_dotted_attribute_ids(self):
        catalog = json.loads(Path('plugins/asset-types-br-catalog/fixtures/default/expected.json').read_text())
        fii = next(item for item in catalog if item['id'] == 'fii')
        p = portfolio()
        p['asset_type_catalog'] = [fii]
        for holding in p['holdings']:
            holding['instrument_attributes'] = {'fund_cnpj': '12345678000190', 'b3_ticker': 'ABCD11', 'fii_type': 'TIJOLO', 'tax_profile.ir_pf_treatment': 'ISENTO'}
        self.assertEqual(self.schema_errors(p), [])
        self.assertEqual(validate_portfolio(p), [])
        p['asset_type_catalog'][0]['id'] = 'invalid.asset.type'
        self.assertTrue(self.schema_errors(p))

    def test_unknown_holding_quantity_is_preserved_but_lots_require_numbers(self):
        p = portfolio()
        p['holdings'][0]['quantity'] = None
        self.assertEqual(self.schema_errors(p), [])
        self.assertEqual(validate_portfolio(p), [])
        statement = {'provider': 'broker', 'generated_at': '2026-01-01T00:00:00Z', 'holdings': [p['holdings'][0]]}
        self.assertEqual(self.schema_errors(statement, 'plugin-statement'), [])
        p['tax_lots'][0]['quantity'] = None
        self.assertTrue(self.schema_errors(p))
        self.assertTrue(any('tax_lots[0].quantity' in error for error in validate_portfolio(p)))
        p['holdings'][0]['market_value']['amount'] = None
        self.assertTrue(self.schema_errors(p))
