from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rikdom.plugin_engine import contract_runner
from rikdom.plugin_engine.contract_runner import (
    CaseResult,
    FixtureCase,
    HOOK_DISPATCH,
    coverage_report,
    discover_fixtures,
    missing_requirements,
    run_case,
    validate_schema,
)


PLUGINS_DIR = Path(__file__).resolve().parents[1] / "plugins"


class PluginContractTests(unittest.TestCase):
    """Exercises every declared Pluggy hook via committed fixtures.

    Each fixture under `plugins/<name>/fixtures/<case>/` runs as a subTest.
    The runner loads the plugin through the real PluginRuntime, invokes the
    declared hook, optionally validates the payload against a canonical
    schema, and asserts byte-identical reruns (determinism). Adding a new
    plugin with a v1 data hook requires adding at least one fixture or the
    coverage check below fails CI.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases: list[FixtureCase] = discover_fixtures(PLUGINS_DIR)

    def test_every_declared_hook_has_a_fixture(self) -> None:
        missing: list[str] = []
        for report in coverage_report(PLUGINS_DIR, self.cases):
            uncovered = sorted(report.declared_hooks - report.covered_hooks)
            for hook in uncovered:
                missing.append(f"{report.plugin_name}:{hook}")
        if missing:
            self.fail(
                "Plugins declare v1 hooks with no contract fixture: "
                + ", ".join(missing)
            )

    def test_at_least_one_fixture_discovered(self) -> None:
        self.assertGreater(
            len(self.cases),
            0,
            "No plugin contract fixtures discovered; contract runner would be a no-op.",
        )

    def test_every_fixture_uses_known_hook(self) -> None:
        for case in self.cases:
            with self.subTest(plugin=case.plugin_name, case=case.case_name):
                self.assertIn(case.hook, HOOK_DISPATCH)

    def test_fixture_cases(self) -> None:
        for case in self.cases:
            with self.subTest(plugin=case.plugin_name, case=case.case_name, hook=case.hook):
                self._run_fixture(case)

    def _run_fixture(self, case: FixtureCase) -> None:
        missing = missing_requirements(case)
        if missing:
            self.skipTest(
                f"Missing optional dependency for fixture {case.plugin_name}/"
                f"{case.case_name}: {', '.join(missing)}"
            )
        with tempfile.TemporaryDirectory(prefix="rikdom-contract-") as tmp1:
            first = run_case(case, PLUGINS_DIR, Path(tmp1))
            self._check_error_contract(case, first)
            if case.expected_error is not None:
                return
            self.assertIsNotNone(first.payload, f"hook {case.hook} returned None")
            self._check_payload_equality(case, first)
            self._check_schema(case, first)

            # Determinism: rerun in a fresh tmpdir and compare normalized
            # canonical JSON bytes. Fixture cases may widen `ignore_fields`
            # to mask fields that legitimately vary (e.g. tmp-path echoes).
            with tempfile.TemporaryDirectory(prefix="rikdom-contract-") as tmp2:
                second = run_case(case, PLUGINS_DIR, Path(tmp2))
                if second.error is not None:
                    raise AssertionError(
                        f"Second run raised {type(second.error).__name__}: {second.error}"
                    )
                self.assertEqual(
                    first.raw_normalized,
                    second.raw_normalized,
                    "Hook output is not byte-identical across reruns (non-deterministic).",
                )

    def _check_error_contract(self, case: FixtureCase, result: CaseResult) -> None:
        expected = case.expected_error
        if expected is None:
            if result.error is not None:
                raise result.error  # surface as test failure
            return
        self.assertIsNotNone(
            result.error,
            "Fixture expected an error but the hook returned a payload.",
        )
        want_type = expected.get("type")
        if want_type:
            self.assertEqual(type(result.error).__name__, want_type)
        want_contains = expected.get("message_contains")
        if want_contains:
            self.assertIn(want_contains, str(result.error))

    def _check_payload_equality(self, case: FixtureCase, result: CaseResult) -> None:
        if case.expected_payload is None:
            return
        expected_normalized = contract_runner._strip_ignored(
            case.expected_payload, set(case.ignore_fields)
        )
        actual_normalized = contract_runner._strip_ignored(
            result.payload, set(case.ignore_fields)
        )
        self.assertEqual(actual_normalized, expected_normalized)

    def _check_schema(self, case: FixtureCase, result: CaseResult) -> None:
        if not case.validate_schema:
            return
        validate_schema(result.payload, case.validate_schema)


if __name__ == "__main__":
    unittest.main()
