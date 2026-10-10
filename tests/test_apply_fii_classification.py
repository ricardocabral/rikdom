import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "apply_fii_classification.py"

spec = importlib.util.spec_from_file_location("apply_fii_classification", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _portfolio() -> dict:
    return {
        "asset_type_catalog": [
            {"id": "reit", "label": "REIT", "asset_class": "reits"},
            {"id": "fund", "label": "Fund", "asset_class": "funds"},
            {"id": "stock", "label": "Stock", "asset_class": "stocks"},
        ],
        "holdings": [
            {
                "id": "h1",
                "asset_type_id": "reit",
                "identifiers": {"ticker": "AAAA11"},
            },
            {
                "id": "h2",
                "asset_type_id": "fund",
                "identifiers": {"ticker": "BBBB11"},
            },
            {
                "id": "h3",
                "asset_type_id": "stock",
                "identifiers": {"ticker": "AAAA11"},
            },
        ],
    }


def _mapping() -> dict:
    return {
        "AAAA11": {"fii_type": "TIJOLO", "segment": "Logistica"},
        "BBBB11": {"fii_type": "PAPEL", "segment": "CRI"},
        "ZZZZ11": {"fii_type": "HIBRIDO", "segment": ""},
    }


class EnsureCatalogAttributesTest(unittest.TestCase):
    def test_adds_optional_attrs_to_reit_and_fund_only(self):
        portfolio = _portfolio()
        added = mod.ensure_catalog_attributes(portfolio)
        self.assertEqual(added, 6)
        by_id = {e["id"]: e for e in portfolio["asset_type_catalog"]}
        for type_id in ("reit", "fund"):
            declared = {a["id"]: a for a in by_id[type_id]["instrument_attributes"]}
            self.assertEqual(
                set(declared), {"fii_type", "segment", "b3_ticker"}
            )
            self.assertFalse(any(a["required"] for a in declared.values()))
            self.assertEqual(declared["fii_type"]["enum"], mod.FII_TYPE_ENUM)
        self.assertNotIn("instrument_attributes", by_id["stock"])

    def test_idempotent(self):
        portfolio = _portfolio()
        mod.ensure_catalog_attributes(portfolio)
        self.assertEqual(mod.ensure_catalog_attributes(portfolio), 0)


class ApplyClassificationTest(unittest.TestCase):
    def test_applies_to_live_types_and_reports_unmatched(self):
        portfolio = _portfolio()
        result = mod.apply_classification(portfolio, _mapping())
        self.assertEqual(sorted(result["applied"]), ["AAAA11", "BBBB11"])
        self.assertEqual(result["unmatched"], ["ZZZZ11"])
        h1, h2, h3 = portfolio["holdings"]
        self.assertEqual(
            h1["instrument_attributes"],
            {"fii_type": "TIJOLO", "segment": "Logistica", "b3_ticker": "AAAA11"},
        )
        self.assertEqual(h2["instrument_attributes"]["fii_type"], "PAPEL")
        # stock-typed holding with same ticker must be left alone
        self.assertNotIn("instrument_attributes", h3)

    def test_second_run_is_noop(self):
        portfolio = _portfolio()
        mod.apply_classification(portfolio, _mapping())
        result = mod.apply_classification(portfolio, _mapping())
        self.assertEqual(result["applied"], [])
        self.assertEqual(sorted(result["unchanged"]), ["AAAA11", "BBBB11"])

    def test_preserves_unrelated_attributes(self):
        portfolio = _portfolio()
        portfolio["holdings"][0]["instrument_attributes"] = {"custom": "x"}
        mod.apply_classification(portfolio, _mapping())
        self.assertEqual(
            portfolio["holdings"][0]["instrument_attributes"]["custom"], "x"
        )


class LoadMappingTest(unittest.TestCase):
    def _write(self, payload: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_loads_valid_mapping(self):
        path = self._write(
            {
                "schema": mod.MAPPING_SCHEMA,
                "classifications": {"aaaa11": {"fii_type": "TIJOLO"}},
            }
        )
        mapping = mod.load_mapping(path)
        self.assertEqual(mapping["AAAA11"]["fii_type"], "TIJOLO")

    def test_rejects_bad_schema(self):
        path = self._write({"schema": "other", "classifications": {}})
        with self.assertRaises(ValueError):
            mod.load_mapping(path)

    def test_rejects_invalid_fii_type(self):
        path = self._write(
            {
                "schema": mod.MAPPING_SCHEMA,
                "classifications": {"AAAA11": {"fii_type": "BRICK"}},
            }
        )
        with self.assertRaises(ValueError):
            mod.load_mapping(path)


if __name__ == "__main__":
    unittest.main()
