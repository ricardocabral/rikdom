from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from rikdom.journal import (
    compact_snapshots,
    rotate_journal,
    select_compacted,
    verify_journal,
)
from rikdom.storage import append_jsonl, load_jsonl


def _snap(ts: datetime, value: float = 100.0) -> dict:
    return {
        "timestamp": ts.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "portfolio_value_base": value,
    }


def _synthetic_history(days: int, *, hourly: bool = False) -> list[dict]:
    base = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    rows: list[dict] = []
    for d in range(days):
        day = base - timedelta(days=d)
        if hourly:
            for h in range(0, 24, 6):
                rows.append(_snap(day.replace(hour=h)))
        else:
            rows.append(_snap(day))
    rows.reverse()
    return rows


class SelectCompactedTests(unittest.TestCase):
    def test_daily_window_preserves_every_day(self) -> None:
        today = date(2026, 4, 20)
        rows = _synthetic_history(10)
        kept = select_compacted(rows, today=today)
        self.assertEqual(len(kept), 10)

    def test_weekly_window_collapses_to_one_per_week(self) -> None:
        today = date(2026, 4, 20)
        # 7 rows inside the week 2026-W01 (well outside 30d daily window).
        week_start = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
        rows = [_snap(week_start + timedelta(days=i, hours=i)) for i in range(7)]
        kept = select_compacted(rows, today=today)
        self.assertEqual(len(kept), 1)
        # Latest in bucket wins.
        self.assertEqual(
            kept[0]["timestamp"],
            (week_start + timedelta(days=6, hours=6))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        )

    def test_monthly_window_collapses_old_rows(self) -> None:
        today = date(2026, 4, 20)
        # Rows from 2024-03: well beyond 1y weekly window.
        month_base = datetime(2024, 3, 1, 10, 0, tzinfo=timezone.utc)
        rows = [_snap(month_base + timedelta(days=i)) for i in range(5)]
        kept = select_compacted(rows, today=today)
        self.assertEqual(len(kept), 1)

    def test_180_day_policy_shape(self) -> None:
        today = date(2026, 4, 20)
        rows = _synthetic_history(180, hourly=True)
        kept = select_compacted(rows, today=today)
        # Daily window (<30d) keeps every row (per-second bucket): 30 * 4 = 120.
        # Weekly window beyond: ~150 days ≈ 22 weeks -> 22 rows kept.
        self.assertLess(len(kept), len(rows))
        self.assertGreaterEqual(len(kept), 120)
        self.assertLessEqual(len(kept), 150)

    def test_orphan_rows_without_timestamp_are_kept(self) -> None:
        rows = [{"note": "no ts"}, _snap(datetime(2026, 4, 20, tzinfo=timezone.utc))]
        kept = select_compacted(rows, today=date(2026, 4, 20))
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0], {"note": "no ts"})

    def test_mixed_naive_and_aware_timestamps_are_compared_in_utc(self) -> None:
        rows = [
            {"timestamp": "2026-01-06T12:00:00", "portfolio_value_base": 1.0},
            {"timestamp": "2026-01-06T09:30:00-03:00", "portfolio_value_base": 2.0},
        ]
        kept = select_compacted(rows, today=date(2026, 4, 20))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["portfolio_value_base"], 2.0)


class CompactSnapshotsTests(unittest.TestCase):
    def test_round_trip_writes_policy_output_and_keeps_backup(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            for row in _synthetic_history(400):
                append_jsonl(path, row)
            before_size = path.stat().st_size
            before_rows = len(load_jsonl(path))

            before, after = compact_snapshots(path)

            self.assertEqual(before, before_rows)
            self.assertLess(after, before)
            self.assertTrue(path.with_name("snapshots.jsonl.bak").exists())
            self.assertEqual(
                path.with_name("snapshots.jsonl.bak").stat().st_size,
                before_size,
            )
            reloaded = load_jsonl(path)
            self.assertEqual(len(reloaded), after)

    def test_atomic_replace_on_failure_leaves_original_intact(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            for row in _synthetic_history(40):
                append_jsonl(path, row)
            original = path.read_bytes()

            with mock.patch("rikdom.journal.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    compact_snapshots(path, keep_backup=False)

            self.assertEqual(path.read_bytes(), original)
            leftovers = [p.name for p in path.parent.iterdir() if p.name.startswith(".snapshots.jsonl.")]
            self.assertEqual(leftovers, [])


class VerifyJournalTests(unittest.TestCase):
    def test_reports_ok_rows_and_torn_tail(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            for i in range(3):
                append_jsonl(path, {"i": i})
            with path.open("ab") as f:
                f.write(b'{"i": 3, "partial')
            result = verify_journal(path)
            self.assertEqual(result.ok_rows, 3)
            self.assertGreater(result.torn_tail_bytes, 0)
            self.assertEqual(result.torn_tail_bytes, len(b'{"i": 3, "partial'))


class RotateJournalTests(unittest.TestCase):
    def test_rotates_when_above_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            for i in range(20):
                append_jsonl(path, {"i": i, "pad": "x" * 200})
            size = path.stat().st_size
            archived = rotate_journal(path, max_bytes=size - 1)
            self.assertIsNotNone(archived)
            self.assertTrue(archived.exists())
            self.assertEqual(path.stat().st_size, 0)

    def test_noop_when_below_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            append_jsonl(path, {"i": 0})
            self.assertIsNone(rotate_journal(path, max_bytes=10_000_000))


class CompactCliTests(unittest.TestCase):
    def test_cli_dry_run_reports_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            for row in _synthetic_history(120):
                append_jsonl(path, row)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rikdom.cli",
                    "compact",
                    "--snapshots",
                    str(path),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "planned")
            self.assertGreater(payload["rows_before"], payload["rows_after"])
            # File untouched.
            self.assertEqual(len(load_jsonl(path)), 120)

    def test_cli_dry_run_with_rotate_does_not_mutate_journal(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            for row in _synthetic_history(120):
                append_jsonl(path, row)
            before = load_jsonl(path)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rikdom.cli",
                    "compact",
                    "--snapshots",
                    str(path),
                    "--dry-run",
                    "--rotate",
                    "--rotate-bytes",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "planned")
            self.assertTrue(payload["rotation"]["would_rotate"])
            self.assertEqual(load_jsonl(path), before)
            self.assertEqual(list(path.parent.glob("snapshots.jsonl.*")), [])

    def test_cli_compact_writes_and_leaves_backup(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            for row in _synthetic_history(120):
                append_jsonl(path, row)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rikdom.cli",
                    "compact",
                    "--snapshots",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "written")
            self.assertTrue(path.with_name("snapshots.jsonl.bak").exists())


if __name__ == "__main__":
    unittest.main()
