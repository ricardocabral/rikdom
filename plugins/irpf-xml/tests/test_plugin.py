from __future__ import annotations

import unittest
from pathlib import Path

from plugin import Plugin, importer_impl


FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample" / "input.xml"


class TestIrpfXmlPlugin(unittest.TestCase):
    def test_parse_statement_emits_expected_holdings(self) -> None:
        payload = importer_impl.parse_statement(FIXTURE)
        self.assertEqual(payload["provider"], "irpf-xml")
        self.assertEqual(payload["base_currency"], "BRL")
        self.assertEqual(payload["metadata"]["irpf_exercicio"], 2026)
        self.assertEqual(payload["metadata"]["current_year_end"], "2025-12-31")
        self.assertEqual(payload["metadata"]["prior_year_end"], "2024-12-31")
        self.assertEqual(len(payload["holdings"]), 7)

    def test_classifies_known_groups(self) -> None:
        payload = importer_impl.parse_statement(FIXTURE)
        by_index = {h["metadata"]["irpf"]["indice"]: h for h in payload["holdings"]}
        self.assertEqual(by_index["00001"]["asset_type_id"], "cash_equivalent")
        self.assertEqual(by_index["00002"]["asset_type_id"], "acao")
        self.assertEqual(by_index["00003"]["asset_type_id"], "fii")
        self.assertEqual(by_index["00004"]["asset_type_id"], "tesouro_direto")
        self.assertEqual(by_index["00005"]["asset_type_id"], "debenture_infra")
        self.assertEqual(by_index["00006"]["asset_type_id"], "fundo_investimento")
        self.assertEqual(by_index["00007"]["asset_type_id"], "real_estate")

    def test_preserves_prior_and_current_year_values(self) -> None:
        payload = importer_impl.parse_statement(FIXTURE)
        fii = next(h for h in payload["holdings"] if h["metadata"]["irpf"]["indice"] == "00003")
        self.assertEqual(fii["market_value"], {"amount": 5500.0, "currency": "BRL"})
        self.assertEqual(
            fii["metadata"]["value_prior_year_end"], {"amount": 5000.0, "currency": "BRL"}
        )
        self.assertEqual(fii["identifiers"]["cnpj"], "22.222.222/0001-22")
        self.assertEqual(fii["identifiers"]["ticker"], "DEMO11")

    def test_ids_are_year_agnostic_and_unique(self) -> None:
        payload = importer_impl.parse_statement(FIXTURE)
        ids = [h["id"] for h in payload["holdings"]]
        self.assertEqual(len(ids), len(set(ids)), "holding ids must be unique within a declaration")
        # The exercicio (declaration year) must NOT appear in the id, so
        # cross-year imports of the same asset land on the same holding.
        for hid in ids:
            self.assertNotIn("2026", hid, f"id leaked declaration year: {hid}")
            self.assertNotIn("2025", hid, f"id leaked declaration year: {hid}")

    def test_id_strategies_match_input(self) -> None:
        payload = importer_impl.parse_statement(FIXTURE)
        by_index = {h["metadata"]["irpf"]["indice"]: h for h in payload["holdings"]}
        self.assertEqual(by_index["00001"]["metadata"]["irpf"]["id_strategy"], "bank_account")
        self.assertEqual(by_index["00002"]["metadata"]["irpf"]["id_strategy"], "ticker")
        self.assertEqual(by_index["00003"]["metadata"]["irpf"]["id_strategy"], "ticker")
        # 04.03 (broker-held debt) — no ticker, broker CNPJ, falls back to hash
        self.assertEqual(by_index["00004"]["metadata"]["irpf"]["id_strategy"], "discriminacao_hash")
        # 07.01 mutual fund with CNPJ
        self.assertEqual(by_index["00006"]["metadata"]["irpf"]["id_strategy"], "issuer_cnpj")

    def test_hook_returns_payload(self) -> None:
        plugin = Plugin()
        payload = plugin.source_input(ctx=None, input_path=FIXTURE)
        self.assertIn("holdings", payload)


if __name__ == "__main__":
    unittest.main()
