from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.cli import main
from rikdom.migrations.policy import (
    POLICY_MIGRATIONS,
    PolicyMigrationPlanError,
    apply_policy_migrations,
    plan_policy_migrations,
)
from rikdom.policy import CURRENT_POLICY_SCHEMA_VERSION, validate_policy
from rikdom.storage import load_json


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data-sample" / "policy.json"


def _load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class PlannerTests(unittest.TestCase):
    def test_noop_at_current_version(self) -> None:
        self.assertEqual(
            plan_policy_migrations(
                CURRENT_POLICY_SCHEMA_VERSION, CURRENT_POLICY_SCHEMA_VERSION
            ),
            [],
        )

    def test_chain_0_1_0_to_current(self) -> None:
        steps = plan_policy_migrations((0, 1, 0), CURRENT_POLICY_SCHEMA_VERSION)
        self.assertEqual(
            [(s.from_version, s.to_version) for s in steps],
            [
                ((0, 1, 0), (0, 2, 0)),
                ((0, 2, 0), (0, 3, 0)),
            ],
        )

    def test_downgrade_rejected(self) -> None:
        with self.assertRaises(PolicyMigrationPlanError):
            plan_policy_migrations((0, 2, 0), (0, 1, 0))

    def test_unknown_source_rejected(self) -> None:
        with self.assertRaises(PolicyMigrationPlanError):
            plan_policy_migrations((9, 9, 9), CURRENT_POLICY_SCHEMA_VERSION)

    def test_registry_is_contiguous(self) -> None:
        for prev, nxt in zip(POLICY_MIGRATIONS, POLICY_MIGRATIONS[1:]):
            self.assertEqual(prev.to_version, nxt.from_version)


class ApplyTests(unittest.TestCase):
    def test_upgrade_from_legacy_010(self) -> None:
        policy = _load_sample()
        policy["schema_version"] = "0.1.0"
        # Strip features added in later policy versions so the input genuinely
        # looks like 0.1.0.
        policy.pop("benchmarks", None)
        policy.pop("tax_rules", None)
        policy.pop("tax_exemptions", None)
        for target in policy["strategic_allocation"]["targets"]:
            target.pop("benchmark_id", None)

        steps = plan_policy_migrations((0, 1, 0), CURRENT_POLICY_SCHEMA_VERSION)
        result, applied = apply_policy_migrations(policy, steps)
        self.assertEqual(result["schema_version"], "0.3.0")
        self.assertEqual(validate_policy(result), [])
        self.assertEqual(len(applied), 2)
        self.assertTrue(any("benchmarks" in c for c in applied[0].changes))
        self.assertTrue(any("tax_rules" in c for c in applied[1].changes))

    def test_idempotent(self) -> None:
        policy = _load_sample()
        steps = plan_policy_migrations(
            CURRENT_POLICY_SCHEMA_VERSION, CURRENT_POLICY_SCHEMA_VERSION
        )
        result, applied = apply_policy_migrations(policy, steps)
        self.assertEqual(applied, [])
        self.assertEqual(result, policy)

    def test_does_not_mutate_input(self) -> None:
        policy = _load_sample()
        policy["schema_version"] = "0.1.0"
        snapshot = copy.deepcopy(policy)
        steps = plan_policy_migrations((0, 1, 0), CURRENT_POLICY_SCHEMA_VERSION)
        apply_policy_migrations(policy, steps)
        self.assertEqual(policy, snapshot)


class CliMigratePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _stage_legacy(self) -> Path:
        target = self.tmp / "policy.json"
        policy = _load_sample()
        policy["schema_version"] = "0.1.0"
        policy.pop("benchmarks", None)
        policy.pop("tax_rules", None)
        policy.pop("tax_exemptions", None)
        for t in policy["strategic_allocation"]["targets"]:
            t.pop("benchmark_id", None)
        target.write_text(json.dumps(policy), encoding="utf-8")
        return target

    def test_dry_run_does_not_write(self) -> None:
        path = self._stage_legacy()
        before = path.read_bytes()
        rc, stdout, _ = _run(
            ["migrate-policy", "--policy", str(path), "--dry-run"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout)["status"], "planned")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.tmp.glob("*.bak-*")), [])

    def test_writes_with_backup_by_default(self) -> None:
        path = self._stage_legacy()
        original = path.read_bytes()
        rc, stdout, _ = _run(["migrate-policy", "--policy", str(path)])
        self.assertEqual(rc, 0, stdout)
        migrated = load_json(path)
        self.assertEqual(migrated["schema_version"], "0.3.0")
        backups = list(self.tmp.glob("policy.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)

    def test_no_backup_flag(self) -> None:
        path = self._stage_legacy()
        rc, _, _ = _run(
            ["migrate-policy", "--policy", str(path), "--no-backup"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(list(self.tmp.glob("*.bak-*")), [])

    def test_noop_at_current(self) -> None:
        path = self.tmp / "policy.json"
        path.write_text(json.dumps(_load_sample()), encoding="utf-8")
        rc, stdout, _ = _run(["migrate-policy", "--policy", str(path)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout)["status"], "noop")


if __name__ == "__main__":
    unittest.main()
