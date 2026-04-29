from __future__ import annotations

import copy
import unittest

from rikdom.migrations import (
    MIGRATIONS,
    MigrationPlanError,
    apply_migrations,
    parse_version,
    plan_migrations,
)
from rikdom.storage import load_json
from rikdom.validate import validate_portfolio


FIXTURE_PATH = "tests/fixtures/portfolio_v1_0_0.json"
CANONICAL_SCHEMA_URI = "https://example.org/rikdom/schema/portfolio.schema.json"


class PlannerTests(unittest.TestCase):
    def test_noop_when_versions_match(self) -> None:
        self.assertEqual(plan_migrations((1, 4, 0), (1, 4, 0)), [])

    def test_full_chain_1_0_0_to_current(self) -> None:
        steps = plan_migrations((1, 0, 0), (1, 4, 0))
        self.assertEqual(
            [(s.from_version, s.to_version) for s in steps],
            [
                ((1, 0, 0), (1, 1, 0)),
                ((1, 1, 0), (1, 2, 0)),
                ((1, 2, 0), (1, 3, 0)),
                ((1, 3, 0), (1, 4, 0)),
            ],
        )

    def test_partial_chain_stops_at_target(self) -> None:
        steps = plan_migrations((1, 0, 0), (1, 1, 0))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].to_version, (1, 1, 0))

    def test_downgrade_rejected(self) -> None:
        with self.assertRaises(MigrationPlanError):
            plan_migrations((1, 4, 0), (1, 0, 0))

    def test_unknown_source_rejected(self) -> None:
        with self.assertRaises(MigrationPlanError):
            plan_migrations((0, 9, 0), (1, 4, 0))

    def test_registry_is_contiguous_chain(self) -> None:
        for prev, nxt in zip(MIGRATIONS, MIGRATIONS[1:]):
            self.assertEqual(prev.to_version, nxt.from_version)


class ApplyTests(unittest.TestCase):
    def test_upgrade_produces_valid_current_portfolio(self) -> None:
        portfolio = load_json(FIXTURE_PATH)
        steps = plan_migrations(parse_version(portfolio["schema_version"]), (1, 4, 0))
        result, applied = apply_migrations(portfolio, steps)

        self.assertEqual(result["schema_version"], "1.4.0")
        self.assertEqual(result["schema_uri"], CANONICAL_SCHEMA_URI)
        self.assertEqual(validate_portfolio(result), [])
        self.assertEqual(len(applied), 4)
        self.assertTrue(any("activities" in c for c in applied[0].changes))

    def test_preserves_unknown_extensions_and_metadata(self) -> None:
        portfolio = load_json(FIXTURE_PATH)
        original_ext = copy.deepcopy(portfolio["extensions"])
        original_meta = copy.deepcopy(portfolio["holdings"][0]["metadata"])

        steps = plan_migrations((1, 0, 0), (1, 4, 0))
        result, _ = apply_migrations(portfolio, steps)

        self.assertEqual(result["extensions"], original_ext)
        self.assertEqual(result["holdings"][0]["metadata"], original_meta)

    def test_does_not_mutate_input(self) -> None:
        portfolio = load_json(FIXTURE_PATH)
        snapshot = copy.deepcopy(portfolio)

        steps = plan_migrations((1, 0, 0), (1, 4, 0))
        apply_migrations(portfolio, steps)

        self.assertEqual(portfolio, snapshot)

    def test_idempotent_when_rerun_at_target(self) -> None:
        portfolio = load_json(FIXTURE_PATH)
        steps = plan_migrations((1, 0, 0), (1, 4, 0))
        upgraded, _ = apply_migrations(portfolio, steps)

        noop_steps = plan_migrations((1, 4, 0), (1, 4, 0))
        second, applied = apply_migrations(upgraded, noop_steps)
        self.assertEqual(applied, [])
        self.assertEqual(second, upgraded)

    def test_v1_3_0_to_v1_4_0_step_announces_new_slots(self) -> None:
        portfolio = load_json(FIXTURE_PATH)
        steps = plan_migrations((1, 0, 0), (1, 4, 0))
        _, applied = apply_migrations(portfolio, steps)
        last = applied[-1]
        self.assertEqual(last.to_version, (1, 4, 0))
        joined = "\n".join(last.changes)
        for token in ("fx_conversion", "tax_lot_ids", "withholding_tax"):
            self.assertIn(token, joined)


if __name__ == "__main__":
    unittest.main()
