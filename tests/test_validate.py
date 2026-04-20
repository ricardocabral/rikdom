from __future__ import annotations

import copy
import unittest

from rikdom.storage import load_json
from rikdom.validate import validate_portfolio


class ValidateTests(unittest.TestCase):
    def test_example_portfolio_is_valid(self) -> None:
        portfolio = load_json("data/portfolio.json")
        errors = validate_portfolio(portfolio)
        self.assertEqual(errors, [])

    def test_operations_event_must_reference_existing_task(self) -> None:
        portfolio = load_json("data/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        candidate["operations"]["task_events"][0]["task_id"] = "unknown-task"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("not in operations.task_catalog" in error for error in errors),
            msg=f"Expected task reference error, got: {errors}",
        )

    def test_operations_last_event_must_exist(self) -> None:
        portfolio = load_json("data/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        candidate["operations"]["task_catalog"][0]["last_event_id"] = "missing-event-id"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("last_event_id" in error and "not in operations.task_events" in error for error in errors),
            msg=f"Expected last_event_id integrity error, got: {errors}",
        )

    def test_missing_required_instrument_attribute_is_invalid(self) -> None:
        portfolio = load_json("data/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        td_holding = next(h for h in candidate["holdings"] if h["id"] == "h-td-ipca")
        del td_holding["instrument_attributes"]["expiration_year"]

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("missing required key 'expiration_year'" in error for error in errors),
            msg=f"Expected required instrument attribute error, got: {errors}",
        )

    def test_instrument_attribute_type_must_match_definition(self) -> None:
        portfolio = load_json("data/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        td_holding = next(h for h in candidate["holdings"] if h["id"] == "h-td-ipca")
        td_holding["instrument_attributes"]["semestral_payments"] = "no"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("instrument_attributes.semestral_payments must be boolean" in error for error in errors),
            msg=f"Expected instrument attribute type error, got: {errors}",
        )


if __name__ == "__main__":
    unittest.main()
