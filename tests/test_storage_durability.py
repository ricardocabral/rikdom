from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from rikdom.storage import append_jsonl, load_jsonl, save_json


class SaveJsonAtomicityTests(unittest.TestCase):
    def test_save_json_leaves_original_on_replace_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            save_json(path, {"ok": 1})
            original = path.read_text(encoding="utf-8")

            with mock.patch("rikdom.storage.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    save_json(path, {"ok": 2})

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            leftovers = [p.name for p in path.parent.iterdir() if p.name.startswith(".portfolio.json.")]
            self.assertEqual(leftovers, [], f"tmp file leaked: {leftovers}")

    def test_save_json_creates_new_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "new.json"
            save_json(path, {"a": 1})
            self.assertEqual(json.loads(path.read_text()), {"a": 1})

    def test_save_json_preserves_existing_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            save_json(path, {"ok": 1})
            os.chmod(path, 0o640)
            original_mode = path.stat().st_mode & 0o7777
            self.assertEqual(original_mode, 0o640)

            save_json(path, {"ok": 2})

            self.assertEqual(path.stat().st_mode & 0o7777, 0o640)
            self.assertEqual(json.loads(path.read_text()), {"ok": 2})

    def test_save_json_fsyncs_parent_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            with mock.patch("rikdom.storage.fsync_dir") as spy:
                save_json(path, {"ok": 1})
            spy.assert_called_once_with(path.parent)


class AppendJsonlDurabilityTests(unittest.TestCase):
    def test_append_then_load_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            for i in range(5):
                append_jsonl(path, {"i": i})
            rows = load_jsonl(path)
            self.assertEqual([r["i"] for r in rows], [0, 1, 2, 3, 4])

    def test_append_retries_until_full_write_on_short_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            real_write = os.write

            def short_write(fd: int, payload: bytes | bytearray | memoryview) -> int:
                chunk = bytes(payload)
                limit = max(1, len(chunk) // 2)
                return real_write(fd, chunk[:limit])

            with mock.patch("rikdom.storage.os.write", side_effect=short_write):
                append_jsonl(path, {"i": 1}, durable=False)

            rows = load_jsonl(path)
            self.assertEqual(rows, [{"i": 1}])

    def test_append_retries_on_interrupted_error(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            real_write = os.write
            raised = {"done": False}

            def interrupted_then_write(fd: int, payload: bytes | bytearray | memoryview) -> int:
                if not raised["done"]:
                    raised["done"] = True
                    raise InterruptedError()
                return real_write(fd, bytes(payload))

            with mock.patch("rikdom.storage.os.write", side_effect=interrupted_then_write):
                append_jsonl(path, {"i": 2}, durable=False)

            rows = load_jsonl(path)
            self.assertEqual(rows, [{"i": 2}])

    def test_load_skips_torn_trailing_line(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            for i in range(3):
                append_jsonl(path, {"i": i})
            with path.open("ab") as f:
                f.write(b'{"i": 3, "partial')
            with self.assertLogs("rikdom.storage", level="WARNING"):
                rows = load_jsonl(path)
            self.assertEqual([r["i"] for r in rows], [0, 1, 2])

    def test_load_skips_malformed_middle_line(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            append_jsonl(path, {"i": 0})
            with path.open("ab") as f:
                f.write(b"not-json\n")
            append_jsonl(path, {"i": 2})
            with self.assertLogs("rikdom.storage", level="WARNING"):
                rows = load_jsonl(path)
            self.assertEqual([r["i"] for r in rows], [0, 2])

    def test_repair_truncates_torn_tail(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            for i in range(2):
                append_jsonl(path, {"i": i})
            good_size = path.stat().st_size
            with path.open("ab") as f:
                f.write(b'{"i": 2, "bad')
            self.assertGreater(path.stat().st_size, good_size)
            load_jsonl(path, repair=True)
            self.assertEqual(path.stat().st_size, good_size)
            # After repair, next append should produce a readable tail.
            append_jsonl(path, {"i": 99})
            rows = load_jsonl(path)
            self.assertEqual([r["i"] for r in rows], [0, 1, 99])


if __name__ == "__main__":
    unittest.main()
