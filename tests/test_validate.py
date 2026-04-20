from __future__ import annotations

import unittest

from rikdom.storage import load_json
from rikdom.validate import validate_portfolio


class ValidateTests(unittest.TestCase):
    def test_example_portfolio_is_valid(self) -> None:
        portfolio = load_json("data/portfolio.json")
        errors = validate_portfolio(portfolio)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
