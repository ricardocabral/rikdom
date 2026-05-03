from __future__ import annotations

import unittest

from rikdom.canonical_key import (
    assign_canonical_keys,
    derive_canonical_key,
    holding_canonical_key,
)
from rikdom.plugins import build_import_diff, merge_holdings


class DeriveCanonicalKeyTests(unittest.TestCase):
    def test_br_acao_uses_lowercase_ticker(self) -> None:
        holding = {
            "asset_type_id": "acao",
            "identifiers": {"ticker": "BBDC4"},
            "jurisdiction": {"country": "BR"},
        }
        self.assertEqual(derive_canonical_key(holding), "br:acao:bbdc4")

    def test_br_generic_stock_aliases_to_acao(self) -> None:
        holding = {
            "asset_type_id": "stock",
            "identifiers": {"ticker": "BBDC4"},
            "jurisdiction": {"country": "BR"},
        }
        self.assertEqual(derive_canonical_key(holding), "br:acao:bbdc4")

    def test_br_fii_and_etf_and_bdr(self) -> None:
        for kind in ("fii", "etf", "bdr"):
            holding = {
                "asset_type_id": kind,
                "identifiers": {"ticker": f"AAA{kind.upper()}"},
                "jurisdiction": {"country": "BR"},
            }
            self.assertEqual(derive_canonical_key(holding), f"br:{kind}:aaa{kind}")

    def test_br_fund_uses_cnpj(self) -> None:
        holding = {
            "asset_type_id": "fund",
            "identifiers": {"cnpj": "30.934.757/0001-13"},
        }
        self.assertEqual(derive_canonical_key(holding), "br:fund:30934757000113")

    def test_us_stock_uses_country_and_ticker(self) -> None:
        holding = {
            "asset_type_id": "stock",
            "identifiers": {"ticker": "VTI"},
            "jurisdiction": {"country": "US"},
        }
        self.assertEqual(derive_canonical_key(holding), "us:stock:vti")

    def test_us_stock_default_region_when_country_missing(self) -> None:
        holding = {"asset_type_id": "stock", "identifiers": {"ticker": "VTI"}}
        self.assertEqual(derive_canonical_key(holding), "us:stock:vti")

    def test_cash_equivalent_uses_currency(self) -> None:
        holding = {
            "asset_type_id": "cash_equivalent",
            "market_value": {"amount": 1000.0, "currency": "USD"},
        }
        self.assertEqual(derive_canonical_key(holding), "cash:usd")

    def test_returns_none_when_no_identifier(self) -> None:
        holding = {"asset_type_id": "other", "label": "Opaque"}
        self.assertIsNone(derive_canonical_key(holding))


class AssignCanonicalKeysTests(unittest.TestCase):
    def test_populates_metadata_canonical_key(self) -> None:
        payload = {
            "holdings": [
                {
                    "id": "h1",
                    "asset_type_id": "acao",
                    "identifiers": {"ticker": "PETR4"},
                    "jurisdiction": {"country": "BR"},
                }
            ]
        }
        n = assign_canonical_keys(payload)
        self.assertEqual(n, 1)
        self.assertEqual(
            payload["holdings"][0]["metadata"]["canonical_key"], "br:acao:petr4"
        )

    def test_does_not_overwrite_importer_supplied_key(self) -> None:
        payload = {
            "holdings": [
                {
                    "id": "h1",
                    "asset_type_id": "acao",
                    "identifiers": {"ticker": "PETR4"},
                    "jurisdiction": {"country": "BR"},
                    "metadata": {"canonical_key": "custom:override"},
                }
            ]
        }
        assign_canonical_keys(payload)
        self.assertEqual(
            payload["holdings"][0]["metadata"]["canonical_key"], "custom:override"
        )


class MergeHoldingsCollapseTests(unittest.TestCase):
    def _holding(self, hid: str, ticker: str, *, amount: float, label: str) -> dict:
        return {
            "id": hid,
            "asset_type_id": "acao",
            "label": label,
            "identifiers": {"ticker": ticker},
            "jurisdiction": {"country": "BR"},
            "market_value": {"amount": amount, "currency": "BRL"},
            "metadata": {"canonical_key": f"br:acao:{ticker.lower()}"},
        }

    def test_collapse_disabled_inserts_duplicate(self) -> None:
        existing = self._holding("b3:acct:bbdc4", "BBDC4", amount=1000, label="B3")
        portfolio = {"holdings": [existing]}
        incoming = {
            "holdings": [
                self._holding("irpf-0301-tk-bbdc4", "BBDC4", amount=1100, label="IRPF")
            ]
        }

        merged, counts = merge_holdings(portfolio, incoming)
        self.assertEqual(counts.inserted, 1)
        self.assertEqual(counts.collapsed, 0)
        self.assertEqual(len(merged["holdings"]), 2)

    def test_collapse_enabled_collapses_via_canonical_key(self) -> None:
        existing = self._holding("b3:acct:bbdc4", "BBDC4", amount=1000, label="B3")
        portfolio = {"holdings": [existing]}
        incoming = {
            "holdings": [
                self._holding("irpf-0301-tk-bbdc4", "BBDC4", amount=1100, label="IRPF")
            ]
        }

        merged, counts = merge_holdings(portfolio, incoming, collapse_canonical=True)

        self.assertEqual(counts.inserted, 0)
        self.assertEqual(counts.collapsed, 1)
        self.assertEqual(len(merged["holdings"]), 1)
        only = merged["holdings"][0]
        self.assertEqual(only["id"], "b3:acct:bbdc4")
        self.assertEqual(only["label"], "IRPF")
        self.assertEqual(only["market_value"]["amount"], 1100)
        self.assertIn("irpf-0301-tk-bbdc4", only["metadata"]["collapsed_from"])
        self.assertEqual(holding_canonical_key(only), "br:acao:bbdc4")
        self.assertEqual(counts.collapses[0]["canonical_key"], "br:acao:bbdc4")

    def test_collapse_does_not_match_when_keys_differ(self) -> None:
        existing = self._holding("b3:acct:bbdc4", "BBDC4", amount=1000, label="B3")
        portfolio = {"holdings": [existing]}
        incoming = {
            "holdings": [
                self._holding("irpf-0301-tk-itub4", "ITUB4", amount=900, label="IRPF")
            ]
        }
        merged, counts = merge_holdings(portfolio, incoming, collapse_canonical=True)
        self.assertEqual(counts.inserted, 1)
        self.assertEqual(counts.collapsed, 0)
        self.assertEqual(len(merged["holdings"]), 2)


class BuildImportDiffCollapseTests(unittest.TestCase):
    def test_dry_run_diff_marks_collapse(self) -> None:
        portfolio = {
            "holdings": [
                {
                    "id": "b3:acct:bbdc4",
                    "asset_type_id": "acao",
                    "identifiers": {"ticker": "BBDC4"},
                    "jurisdiction": {"country": "BR"},
                    "market_value": {"amount": 1000, "currency": "BRL"},
                    "metadata": {"canonical_key": "br:acao:bbdc4"},
                }
            ]
        }
        imported = {
            "holdings": [
                {
                    "id": "irpf-0301-tk-bbdc4",
                    "asset_type_id": "acao",
                    "identifiers": {"ticker": "BBDC4"},
                    "jurisdiction": {"country": "BR"},
                    "market_value": {"amount": 1100, "currency": "BRL"},
                    "metadata": {"canonical_key": "br:acao:bbdc4"},
                }
            ]
        }

        without = build_import_diff(portfolio, imported)
        self.assertEqual(without["summary"]["holdings"]["create"], 1)

        with_collapse = build_import_diff(portfolio, imported, collapse_canonical=True)
        rows = with_collapse["rows"]
        self.assertEqual(with_collapse["summary"]["holdings"]["update"], 1)
        self.assertEqual(rows[0]["operation"], "update")
        self.assertEqual(rows[0]["collapsed_canonical_key"], "br:acao:bbdc4")
        self.assertEqual(rows[0]["collapsed_into_id"], "b3:acct:bbdc4")


if __name__ == "__main__":
    unittest.main()
