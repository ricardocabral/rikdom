from __future__ import annotations

import unittest

from rikdom.aggregate import aggregate_portfolio
from rikdom.storage import load_json


class AggregateTests(unittest.TestCase):
    def test_aggregate_total(self) -> None:
        portfolio = load_json("data-sample/portfolio.json")
        result = aggregate_portfolio(portfolio)
        self.assertEqual(result.base_currency, "BRL")
        self.assertAlmostEqual(result.total_value_base, 165830.0)
        self.assertIn("stocks", result.by_asset_class)


if __name__ == "__main__":
    unittest.main()
