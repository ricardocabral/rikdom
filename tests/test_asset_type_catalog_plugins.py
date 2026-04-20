from __future__ import annotations

import unittest

from rikdom.plugin_engine.contracts import BRAZIL_CNPJ_REGEX, BRAZIL_INDEXER_ENUM
from rikdom.plugin_engine.loader import discover_plugins
from rikdom.plugin_engine.pipeline import build_asset_type_catalog


class AssetTypeCatalogPluginTests(unittest.TestCase):
    def test_brazil_catalog_plugin_is_discoverable(self) -> None:
        manifests = discover_plugins("plugins")
        by_name = {item.name: item for item in manifests}

        self.assertIn("asset-types-br-catalog", by_name)
        self.assertIn("asset-type/catalog", by_name["asset-types-br-catalog"].plugin_types)

    def test_wave_1_roadmap_ids_are_available(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        ids = {item["id"] for item in catalog}
        expected = {"fii", "tesouro_direto", "lci", "lca", "cri", "cra"}
        self.assertTrue(expected.issubset(ids), msg=f"Missing ids: {sorted(expected - ids)}")

    def test_wave_2_roadmap_ids_are_available(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        ids = {item["id"] for item in catalog}
        expected = {"debenture_incentivada", "debenture_infra", "bdr", "coe"}
        self.assertTrue(expected.issubset(ids), msg=f"Missing ids: {sorted(expected - ids)}")

    def test_wave_3_roadmap_ids_are_available(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        ids = {item["id"] for item in catalog}
        expected = {"fidc_cota", "fiagro_cota"}
        self.assertTrue(expected.issubset(ids), msg=f"Missing ids: {sorted(expected - ids)}")

    def test_convention_fields_include_cnpj_pattern_and_indexer_enum(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        by_id = {item["id"]: item for item in catalog}

        debt_with_issuer = ("lci", "lca", "debenture_incentivada", "debenture_infra")
        for asset_id in debt_with_issuer:
            attrs = {a["id"]: a for a in by_id[asset_id]["instrument_attributes"]}
            self.assertEqual(attrs["issuer_cnpj"].get("pattern"), BRAZIL_CNPJ_REGEX)
            self.assertEqual(attrs["indexer"].get("enum"), BRAZIL_INDEXER_ENUM)
            self.assertIn("tax_profile.ir_pf_treatment", attrs)
            self.assertIn("tax_profile.source_rule_ref", attrs)

        for asset_id in ("cri", "cra"):
            attrs = {a["id"]: a for a in by_id[asset_id]["instrument_attributes"]}
            self.assertEqual(attrs["securitizadora_cnpj"].get("pattern"), BRAZIL_CNPJ_REGEX)
            self.assertEqual(attrs["indexer"].get("enum"), BRAZIL_INDEXER_ENUM)
            self.assertIn("tax_profile.ir_pf_treatment", attrs)
            self.assertIn("tax_profile.source_rule_ref", attrs)

    def test_type_specific_attributes_are_encoded(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        by_id = {item["id"]: item for item in catalog}

        bdr_attrs = {a["id"] for a in by_id["bdr"]["instrument_attributes"]}
        self.assertTrue(
            {"bdr_level", "depositary_cnpj", "underlying_identifier", "parity_ratio"}.issubset(bdr_attrs)
        )

        coe_attrs = {a["id"] for a in by_id["coe"]["instrument_attributes"]}
        self.assertTrue({"modalidade", "underlying_reference", "payoff_formula"}.issubset(coe_attrs))

        fidc_attrs = {a["id"] for a in by_id["fidc_cota"]["instrument_attributes"]}
        self.assertTrue({"class_id", "subclass_type", "open_closed"}.issubset(fidc_attrs))

        fiagro_attrs = {a["id"] for a in by_id["fiagro_cota"]["instrument_attributes"]}
        self.assertTrue({"class_id", "target_chain", "fiagro_strategy"}.issubset(fiagro_attrs))

    def test_lifecycle_fields_are_present_for_credit_and_securitized_assets(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        by_id = {item["id"]: item for item in catalog}

        for asset_id in (
            "tesouro_direto",
            "lci",
            "lca",
            "cri",
            "cra",
            "debenture_incentivada",
            "debenture_infra",
            "coe",
        ):
            attrs = {a["id"] for a in by_id[asset_id]["instrument_attributes"]}
            self.assertIn("issue_date", attrs)
            self.assertIn("maturity_date", attrs)


if __name__ == "__main__":
    unittest.main()
