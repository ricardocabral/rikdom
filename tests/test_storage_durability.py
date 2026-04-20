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


class AppendJsonlDurabilityTests(unittest.TestCase):
    def test_append_then_load_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            for i in range(5):
                append_jsonl(path, {"i": i})
            rows = load_jsonl(path)
            self.assertEqual([r["i"] for r in rows], [0, 1, 2, 3, 4])

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
