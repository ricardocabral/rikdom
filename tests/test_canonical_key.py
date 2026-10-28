from __future__ import annotations

import unittest

from rikdom.canonical_key import (
    holding_canonical_key,
)
from rikdom.plugins import build_import_diff, merge_holdings


class CanonicalKeyTests(unittest.TestCase):
    def test_identifiers_never_imply_a_key(self) -> None:
        for country in (None, "BR", "US", "JP"):
            holding = {"asset_type_id": "stock", "identifiers": {"ticker": "VTI"}}
            if country:
                holding["jurisdiction"] = {"country": country}
            self.assertIsNone(holding_canonical_key(holding))

    def test_key_is_opaque_and_unknown_metadata_survives(self) -> None:
        holding = {"metadata": {"canonical_key": "  venue:any value  ", "custom": {"x": 1}}}
        self.assertEqual(holding_canonical_key(holding), "  venue:any value  ")
        self.assertEqual(holding["metadata"]["custom"], {"x": 1})

    def test_blank_or_nonstring_key_is_absent(self) -> None:
        for key in (None, "", "   ", 0, [], {}):
            self.assertIsNone(holding_canonical_key({"metadata": {"canonical_key": key}}))


class MergeHoldingsCollapseTests(unittest.TestCase):
    def _holding(self, hid: str, ticker: str, *, amount: float, label: str) -> dict:
        return {
            "id": hid,
            "account_id": "broker-account",
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
                    "account_id": "broker-account",
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
                    "account_id": "broker-account",
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
