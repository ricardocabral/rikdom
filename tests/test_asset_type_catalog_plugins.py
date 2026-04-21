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

    def test_wave_4_roadmap_ids_are_available(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        ids = {item["id"] for item in catalog}
        expected = {"acao", "etf", "cdb", "lig", "lf", "debenture", "fundo_investimento", "previdencia_privada"}
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

    def test_new_assets_required_fields_are_encoded(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        by_id = {item["id"]: item for item in catalog}

        acao_attrs = {a["id"]: a for a in by_id["acao"]["instrument_attributes"]}
        self.assertTrue(acao_attrs["share_class"]["required"])
        self.assertEqual(acao_attrs["share_class"].get("enum"), ["ON", "PN", "PNA", "PNB", "UNIT"])

        etf_attrs = {a["id"]: a for a in by_id["etf"]["instrument_attributes"]}
        self.assertTrue(etf_attrs["underlying_class"]["required"])
        self.assertEqual(
            etf_attrs["underlying_class"].get("enum"),
            ["RENDA_VARIAVEL", "RENDA_FIXA", "CRIPTO", "COMMODITIES", "INTERNACIONAL"],
        )

        fund_attrs = {a["id"]: a for a in by_id["fundo_investimento"]["instrument_attributes"]}
        self.assertTrue(fund_attrs["category"]["required"])
        self.assertEqual(
            fund_attrs["category"].get("enum"),
            ["RENDA_FIXA", "MULTIMERCADO", "ACOES", "CAMBIAL", "FIC", "FIDC", "PREVIDENCIARIO"],
        )

        prev_attrs = {a["id"]: a for a in by_id["previdencia_privada"]["instrument_attributes"]}
        self.assertTrue(prev_attrs["plan_type"]["required"])
        self.assertEqual(prev_attrs["plan_type"].get("enum"), ["PGBL", "VGBL"])
        self.assertTrue(prev_attrs["provider_cnpj"]["required"])
        self.assertEqual(prev_attrs["provider_cnpj"].get("pattern"), BRAZIL_CNPJ_REGEX)
        self.assertTrue(prev_attrs["tax_regime"]["required"])
        self.assertEqual(prev_attrs["tax_regime"].get("enum"), ["PROGRESSIVO", "REGRESSIVO"])

    def test_debenture_regime_constraints_are_encoded(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        by_id = {item["id"]: item for item in catalog}

        debenture_attrs = {a["id"]: a for a in by_id["debenture"]["instrument_attributes"]}
        self.assertIn("tax_benefit_regime", debenture_attrs)
        self.assertFalse(debenture_attrs["tax_benefit_regime"]["required"])
        self.assertEqual(debenture_attrs["tax_benefit_regime"].get("enum"), ["NAO_INCENTIVADA"])

        incentivada_attrs = {a["id"]: a for a in by_id["debenture_incentivada"]["instrument_attributes"]}
        self.assertIn("tax_benefit_regime", incentivada_attrs)
        self.assertTrue(incentivada_attrs["tax_benefit_regime"]["required"])
        self.assertEqual(incentivada_attrs["tax_benefit_regime"].get("enum"), ["LEI_12431"])

        infra_attrs = {a["id"]: a for a in by_id["debenture_infra"]["instrument_attributes"]}
        self.assertIn("tax_benefit_regime", infra_attrs)
        self.assertTrue(infra_attrs["tax_benefit_regime"]["required"])
        self.assertEqual(infra_attrs["tax_benefit_regime"].get("enum"), ["LEI_14801"])

    def test_bdr_underlying_fields_patterns_are_encoded(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        by_id = {item["id"]: item for item in catalog}

        attrs = {a["id"]: a for a in by_id["bdr"]["instrument_attributes"]}
        self.assertEqual(attrs["underlying_country"].get("pattern"), r"^[A-Z]{2}$")
        self.assertEqual(attrs["underlying_isin"].get("pattern"), r"^[A-Z]{2}[A-Z0-9]{9}\d$")

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

    def test_credit_and_securitized_assets_do_not_share_attribute_instances(self) -> None:
        catalog = build_asset_type_catalog("plugins")
        by_id = {item["id"]: item for item in catalog}

        pairs = [
            ("lci", "lca"),
            ("lci", "debenture"),
            ("debenture", "debenture_incentivada"),
            ("debenture_incentivada", "debenture_infra"),
            ("cri", "cra"),
        ]

        for left_id, right_id in pairs:
            left_attrs = by_id[left_id]["instrument_attributes"]
            right_attrs = by_id[right_id]["instrument_attributes"]
            self.assertIsNot(left_attrs, right_attrs)

            left_by_attr_id = {attr["id"]: attr for attr in left_attrs}
            right_by_attr_id = {attr["id"]: attr for attr in right_attrs}
            shared_attr_ids = set(left_by_attr_id) & set(right_by_attr_id)

            for attr_id in shared_attr_ids:
                left_attr = left_by_attr_id[attr_id]
                right_attr = right_by_attr_id[attr_id]
                self.assertIsNot(left_attr, right_attr, msg=f"{left_id}/{right_id} shared '{attr_id}' dict")
                if "enum" in left_attr and "enum" in right_attr:
                    self.assertIsNot(
                        left_attr["enum"],
                        right_attr["enum"],
                        msg=f"{left_id}/{right_id} shared '{attr_id}' enum list",
                    )


if __name__ == "__main__":
    unittest.main()
