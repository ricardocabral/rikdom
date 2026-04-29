from __future__ import annotations

import io
import json
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.cli import main
from rikdom.storage import load_json


FIXTURE = Path("tests/fixtures/portfolio_v1_0_0.json")
CURRENT_FIXTURE = Path("tests/fixtures/portfolio.json")
CANONICAL_SCHEMA_URI = "https://example.org/rikdom/schema/portfolio.schema.json"


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class MigrateCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _stage(self, fixture: Path) -> Path:
        target = self.tmp / "portfolio.json"
        shutil.copy2(fixture, target)
        return target

    def test_noop_when_already_at_current(self) -> None:
        portfolio_path = self._stage(CURRENT_FIXTURE)
        before = portfolio_path.stat().st_mtime_ns

        code, stdout, _ = _run(["migrate", "--portfolio", str(portfolio_path)])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "noop")
        self.assertEqual(portfolio_path.stat().st_mtime_ns, before)
        self.assertEqual(list(self.tmp.glob("*.bak-*")), [])

    def test_dry_run_does_not_write_or_backup(self) -> None:
        portfolio_path = self._stage(FIXTURE)
        before_bytes = portfolio_path.read_bytes()

        code, stdout, _ = _run(
            ["migrate", "--portfolio", str(portfolio_path), "--dry-run"]
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "planned")
        self.assertEqual(payload["from"], "1.0.0")
        self.assertEqual(payload["to"], "1.4.0")
        self.assertEqual(len(payload["steps"]), 4)
        self.assertEqual(portfolio_path.read_bytes(), before_bytes)
        self.assertEqual(list(self.tmp.glob("*.bak-*")), [])

    def test_writes_with_backup_by_default(self) -> None:
        portfolio_path = self._stage(FIXTURE)
        original_bytes = portfolio_path.read_bytes()

        code, stdout, _ = _run(["migrate", "--portfolio", str(portfolio_path)])

        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "written")

        migrated = load_json(portfolio_path)
        self.assertEqual(migrated["schema_version"], "1.4.0")
        self.assertEqual(migrated["schema_uri"], CANONICAL_SCHEMA_URI)
        self.assertEqual(migrated["extensions"], {"com.example.custom": {"flavor": "legacy", "keep_me": True}})

        backups = list(self.tmp.glob("portfolio.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original_bytes)

    def test_no_backup_flag_skips_sibling(self) -> None:
        portfolio_path = self._stage(FIXTURE)

        code, _, _ = _run(
            ["migrate", "--portfolio", str(portfolio_path), "--no-backup"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(list(self.tmp.glob("*.bak-*")), [])

    def test_output_flag_leaves_source_untouched_and_skips_backup(self) -> None:
        portfolio_path = self._stage(FIXTURE)
        original_bytes = portfolio_path.read_bytes()
        out_path = self.tmp / "migrated.json"

        code, _, _ = _run(
            [
                "migrate",
                "--portfolio",
                str(portfolio_path),
                "--output",
                str(out_path),
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(portfolio_path.read_bytes(), original_bytes)
        self.assertEqual(load_json(out_path)["schema_version"], "1.4.0")
        self.assertEqual(list(self.tmp.glob("*.bak-*")), [])

    def test_output_same_as_portfolio_keeps_backup_behavior(self) -> None:
        portfolio_path = self._stage(FIXTURE)
        original_bytes = portfolio_path.read_bytes()

        code, stdout, _ = _run(
            [
                "migrate",
                "--portfolio",
                str(portfolio_path),
                "--output",
                str(portfolio_path),
            ]
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "written")
        backups = list(self.tmp.glob("portfolio.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original_bytes)

    def test_missing_schema_uri_is_migrated(self) -> None:
        portfolio_path = self._stage(FIXTURE)
        data = load_json(portfolio_path)
        data.pop("schema_uri", None)
        portfolio_path.write_text(json.dumps(data), encoding="utf-8")

        code, stdout, _ = _run(["migrate", "--portfolio", str(portfolio_path)])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "written")
        migrated = load_json(portfolio_path)
        self.assertEqual(migrated["schema_uri"], CANONICAL_SCHEMA_URI)

    def test_rejects_invalid_portfolio(self) -> None:
        portfolio_path = self._stage(FIXTURE)
        data = load_json(portfolio_path)
        del data["holdings"]
        portfolio_path.write_text(json.dumps(data), encoding="utf-8")

        code, _, stderr = _run(["migrate", "--portfolio", str(portfolio_path)])

        self.assertEqual(code, 1)
        self.assertIn("Refusing to migrate", stderr)

    def test_rejects_invalid_target(self) -> None:
        portfolio_path = self._stage(FIXTURE)
        code, _, stderr = _run(
            ["migrate", "--portfolio", str(portfolio_path), "--to", "not.a.semver"]
        )
        self.assertEqual(code, 1)
        self.assertIn("Invalid --to", stderr)


if __name__ == "__main__":
    unittest.main()
