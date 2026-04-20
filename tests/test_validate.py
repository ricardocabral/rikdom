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


if __name__ == "__main__":
    unittest.main()
