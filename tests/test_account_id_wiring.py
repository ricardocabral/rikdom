from __future__ import annotations

import unittest

from rikdom.aggregate import UNASSIGNED_ACCOUNT, aggregate_portfolio
from rikdom.storage import load_json
from rikdom.validate import (
    collect_policy_account_ids,
    cross_validate_account_ids,
)


def _minimal_portfolio() -> dict:
    return {
        "schema_version": "1.3.0",
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
                "account_id": "br-taxable-main",
                "label": "A",
                "market_value": {"amount": 100.0, "currency": "BRL"},
            },
            {
                "id": "h2",
                "asset_type_id": "stock",
                "account_id": "br-pgbl",
                "label": "B",
                "market_value": {"amount": 200.0, "currency": "BRL"},
            },
            {
                "id": "h3",
                "asset_type_id": "stock",
                "label": "C-unassigned",
                "market_value": {"amount": 50.0, "currency": "BRL"},
            },
        ],
    }


def _minimal_policy() -> dict:
    return {
        "accounts": [
            {"account_id": "br-taxable-main"},
            {"account_id": "br-pgbl"},
        ],
    }


class CollectPolicyAccountIdsTests(unittest.TestCase):
    def test_collects_declared_ids(self) -> None:
        ids = collect_policy_account_ids(_minimal_policy())
        self.assertEqual(ids, {"br-taxable-main", "br-pgbl"})

    def test_missing_or_invalid_policy_yields_empty(self) -> None:
        self.assertEqual(collect_policy_account_ids(None), set())
        self.assertEqual(collect_policy_account_ids({}), set())
        self.assertEqual(collect_policy_account_ids({"accounts": "x"}), set())


class CrossValidateAccountIdsTests(unittest.TestCase):
    def test_unknown_account_id_is_error(self) -> None:
        portfolio = _minimal_portfolio()
        portfolio["holdings"][0]["account_id"] = "ghost-account"
        errors, _ = cross_validate_account_ids(portfolio, _minimal_policy())
        self.assertTrue(any("ghost-account" in e for e in errors))

    def test_unassigned_holding_emits_warning(self) -> None:
        errors, warnings = cross_validate_account_ids(
            _minimal_portfolio(), _minimal_policy()
        )
        self.assertEqual(errors, [])
        self.assertTrue(any("h3" in w or "holdings[2]" in w for w in warnings))

    def test_no_policy_means_no_check(self) -> None:
        errors, warnings = cross_validate_account_ids(_minimal_portfolio(), {})
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_liabilities_and_tax_lots_account_ids_are_checked(self) -> None:
        portfolio = _minimal_portfolio()
        portfolio["liabilities"] = [
            {
                "id": "lia-1",
                "kind": "mortgage",
                "balance": {"amount": 1.0, "currency": "BRL"},
                "account_id": "ghost-mortgage",
            }
        ]
        portfolio["tax_lots"] = [
            {
                "id": "lot-1",
                "holding_id": "h1",
                "acquired_at": "2026-01-02T00:00:00Z",
                "quantity": 10,
                "cost_basis": {"amount": 100, "currency": "BRL"},
                "account_id": "ghost-lot",
            }
        ]
        errors, _ = cross_validate_account_ids(portfolio, _minimal_policy())
        self.assertTrue(any("ghost-mortgage" in e for e in errors))
        self.assertTrue(any("ghost-lot" in e for e in errors))


class AggregateByAccountTests(unittest.TestCase):
    def test_per_account_rollup(self) -> None:
        result = aggregate_portfolio(_minimal_portfolio())
        self.assertEqual(result.by_account.get("br-taxable-main"), 100.0)
        self.assertEqual(result.by_account.get("br-pgbl"), 200.0)
        self.assertEqual(result.by_account.get(UNASSIGNED_ACCOUNT), 50.0)
        self.assertAlmostEqual(
            sum(result.by_account.values()), result.total_value_base
        )

    def test_sample_portfolio_by_account_matches_policy(self) -> None:
        portfolio = load_json("data-sample/portfolio.json")
        result = aggregate_portfolio(portfolio)
        self.assertNotIn(UNASSIGNED_ACCOUNT, result.by_account)
        for key in ("br-taxable-main", "br-pgbl", "us-offshore"):
            self.assertIn(key, result.by_account)
        self.assertAlmostEqual(
            sum(result.by_account.values()), result.total_value_base, places=2
        )


if __name__ == "__main__":
    unittest.main()
