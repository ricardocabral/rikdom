import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from rikdom.cli import main
from rikdom.storage import load_json, save_json
from tests.test_quantity_coverage import portfolio as quantity_portfolio


ROOT = Path(__file__).resolve().parents[1]


class CliActivityCorrectionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.data = self.path / "data"
        self.p = self.data / "portfolio.json"
        p = load_json(ROOT / "tests/fixtures/portfolio.json")
        fixture = quantity_portfolio()
        p.update({k: copy.deepcopy(fixture[k]) for k in ("settings", "holdings", "activities", "extensions")})
        p["activities"][0]["idempotency_key"] = "a"
        p["activities"][0]["money"] = {"amount": 100, "currency": "JPY"}
        save_json(self.p, p)
        self.input = self.path / "replacement.json"
        replacement = {**p["activities"][0], "id": "replacement", "quantity": 3}
        replacement.pop("idempotency_key")
        save_json(self.input, replacement)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([*args, "--data-dir", str(self.data), "--out-root", str(self.path / "out"), "--plugins-dir", str(ROOT / "plugins")])
        return code, out.getvalue(), err.getvalue()

    def test_preview_write_replay_and_source_reimport_preserve_original(self):
        before = self.p.read_bytes()
        args = ["activity", "correct", "a", "--input", str(self.input), "--reason", "Verified quantity"]
        code, output, err = self.run_cli(*args)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.p.read_bytes(), before)
        self.assertFalse((self.path / "out").exists())
        self.assertFalse((self.data / "import_log.jsonl").exists())
        self.assertEqual(json.loads(output)["contract_transition"]["to"], "2.0.0")
        code, _, err = self.run_cli(*args, "--write")
        self.assertEqual(code, 0, err)
        after = load_json(self.p)
        self.assertEqual(after["schema_version"], "2.0.0")
        self.assertEqual(after["activities"][0], json.loads(before)["activities"][0])
        self.assertEqual(len(after["activities"]), 2)
        code, output, err = self.run_cli(*args, "--write")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(output)["activities"]["skipped"], 1)
        self.assertEqual(len(load_json(self.p)["activities"]), 2)

    def test_copied_idempotency_key_is_rejected_without_writes(self):
        value = load_json(self.input)
        value["idempotency_key"] = "a"
        save_json(self.input, value)
        before = self.p.read_bytes()
        code, _, _ = self.run_cli("activity", "correct", "a", "--input", str(self.input), "--reason", "Reviewed", "--write")
        self.assertEqual(code, 1)
        self.assertEqual(self.p.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
