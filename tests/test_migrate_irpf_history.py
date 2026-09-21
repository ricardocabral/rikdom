from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_irpf_history.py"

SAMPLE_IRPF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<classe xmlns="http://www.receita.fazenda.gov.br/declaracao" dataHoraSalvamento="31/12/2025 12:00:00">
  <bens>
    <item grupo="03" codigo="01" indice="00001" codigoNegociacao="DEMO3" discriminacao="Acao sintetica" valorExercicioAnterior="100,00" valorExercicioAtual="120,00" />
  </bens>
</classe>
"""


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_irpf_history", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrateIrpfHistoryTests(unittest.TestCase):
    def test_archives_only_zero_value_irpf_rows(self) -> None:
        """A historical IRPF row must not remain active, but a live row must."""
        module = _load_module()
        portfolio = {
            "holdings": [
                {"id": "irpf-0301-tk-demo3", "market_value": {"amount": 0, "currency": "BRL"}},
                {"id": "irpf-0701-cnpj-active", "market_value": {"amount": 10, "currency": "BRL"}},
                {"id": "b3:current", "market_value": {"amount": 20, "currency": "BRL"}},
            ]
        }

        active, archived = module.split_active_holdings(portfolio)

        self.assertEqual(
            [holding["id"] for holding in active["holdings"]],
            ["irpf-0701-cnpj-active", "b3:current"],
        )
        self.assertEqual([holding["id"] for holding in archived], ["irpf-0301-tk-demo3"])
        self.assertEqual(portfolio["holdings"][0]["id"], "irpf-0301-tk-demo3")

    def test_dry_run_leaves_portfolio_and_archive_unchanged(self) -> None:
        """A preview must never write either the active portfolio or archive."""
        module = _load_module()
        original = {"holdings": [{"id": "irpf-0301-tk-demo3", "market_value": {"amount": 0, "currency": "BRL"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio_path = root / "portfolio.json"
            archive_path = root / "irpf-history.json"
            fixture = root / "declaracao.xml"
            portfolio_path.write_text(json.dumps(original), encoding="utf-8")
            fixture.write_text(SAMPLE_IRPF_XML, encoding="utf-8")

            result = module.run_migration(portfolio_path, fixture, archive_path, write=False)

            self.assertEqual(json.loads(portfolio_path.read_text(encoding="utf-8")), original)
            self.assertFalse(archive_path.exists())
            self.assertEqual(result["archived_count"], 1)

    def test_enriches_active_fund_and_declares_vehicle_type(self) -> None:
        """Active legacy funds need valid attributes without altering their value."""
        module = _load_module()
        portfolio = {
            "asset_type_catalog": [],
            "holdings": [{
                "id": "irpf-0701-cnpj-37368116000198",
                "asset_type_id": "fundo_investimento",
                "label": "ARX ELBRUS PRO INCENTIVADO INFRA FIRF",
                "identifiers": {"cnpj": "37.368.116/0001-98"},
                "market_value": {"amount": 10, "currency": "BRL"},
            }],
        }
        enriched = module.enrich_active_legacy_holdings(portfolio)
        holding = enriched["holdings"][0]
        self.assertEqual(holding["market_value"]["amount"], 10)
        self.assertEqual(holding["instrument_attributes"]["category"], "RENDA_FIXA")
        self.assertEqual(holding["instrument_attributes"]["tax_profile.ir_pf_treatment"], "OUTRO")
        self.assertTrue(any(item["id"] == "vehicle" for item in enriched["asset_type_catalog"]))


if __name__ == "__main__":
    unittest.main()
