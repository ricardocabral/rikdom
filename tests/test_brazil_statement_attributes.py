import copy
import json
from pathlib import Path
import unittest

from rikdom.plugin_engine.pipeline import build_asset_type_catalog
from rikdom.validate import validate_portfolio


class BrazilStatementAttributeTests(unittest.TestCase):
    def test_cdi_multiplier_and_repo_underlying_are_validated_without_invented_cnpj(self):
        portfolio = json.loads(Path("tests/fixtures/portfolio.json").read_text())
        portfolio["asset_type_catalog"] = build_asset_type_catalog("plugins")
        portfolio["holdings"] = [{
            "id": "repo", "asset_type_id": "compromissada", "label": "Synthetic repo",
            "market_value": {"amount": 100, "currency": "BRL"},
            "jurisdiction": {"country": "BR"},
            "instrument_attributes": {"issuer_name": "Synthetic bank", "underlying_code": "CRA-SYNTHETIC", "indexer_multiplier_pct": 70},
        }]
        portfolio.pop("activities", None)
        portfolio.pop("tax_lots", None)
        self.assertEqual(validate_portfolio(portfolio), [])
        malformed = copy.deepcopy(portfolio)
        malformed["holdings"][0]["instrument_attributes"]["indexer_multiplier_pct"] = "CDI + 70"
        self.assertTrue(any("indexer_multiplier_pct" in e for e in validate_portfolio(malformed)))
