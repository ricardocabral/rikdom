from __future__ import annotations

import io
import hashlib
import json
import os
import subprocess
import sys
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rikdom.cli import main


def run_cli(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main(args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class AnalysisBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.portfolio = self.root / "portfolio.json"
        portfolio = json.loads(Path("tests/fixtures/portfolio.json").read_text())
        portfolio["activities"] = []
        portfolio["holdings"] = [
            {
                "id": "usd",
                "asset_type_id": "stock",
                "label": "USD holding",
                "market_value": {"amount": 10, "currency": "USD"},
                "as_of": "2026-01-01T00:00:00Z",
            },
            {
                "id": "brl",
                "asset_type_id": "stock",
                "label": "BRL holding",
                "market_value": {"amount": 20, "currency": "BRL"},
                "as_of": "2026-01-01T00:00:00Z",
            },
        ]
        self.portfolio.write_text(json.dumps(portfolio))
        self.fx = self.root / "fx_rates.jsonl"
        self.fx.write_text(
            '{"as_of_date":"2026-01-01","base_currency":"BRL",'
            '"quote_currency":"USD","rate_to_base":5,"source":"manual"}\n'
            '{"as_of_date":"2099-01-01","base_currency":"BRL",'
            '"quote_currency":"USD","rate_to_base":500,"source":"future"}\n'
        )
        self.bundle = self.root / "analysis.zip"

    def capture(self, *extra: str) -> tuple[int, str, str]:
        return run_cli(
            [
                "aggregate",
                "--portfolio",
                str(self.portfolio),
                "--fx-history",
                str(self.fx),
                "--bundle",
                str(self.bundle),
                *extra,
            ]
        )

    def replay(self, target: Path | None = None) -> tuple[int, str, str]:
        return run_cli(
            [
                "replay-export",
                "--bundle",
                str(self.bundle),
                "--restore-dir",
                str(target or self.root / "restored"),
            ]
        )

    def rewrite(self, mutate) -> None:
        with zipfile.ZipFile(self.bundle) as archive:
            payloads = {name: archive.read(name) for name in archive.namelist()}
        mutate(payloads)
        manifest = json.loads(payloads["rikdom-export.json"])
        manifest["entries"] = [
            entry for entry in manifest["entries"] if entry["path"] in payloads
        ]
        for entry in manifest["entries"]:
            data = payloads[entry["path"]]
            entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        payloads["rikdom-export.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.bundle, "w") as archive:
            for name, data in payloads.items():
                archive.writestr(name, data)

    def change_run(self, field: str, value) -> None:
        def mutate(payloads):
            run = json.loads(payloads["analysis/run.json"])
            run[field] = value
            payloads["analysis/run.json"] = json.dumps(run).encode()

        self.rewrite(mutate)

    def test_capture_restore_replays_hand_checked_total_in_offline_process(
        self,
    ) -> None:
        code, stdout, stderr = self.capture()
        self.assertEqual((code, stderr), (0, ""))
        captured = json.loads(stdout)
        self.assertEqual(captured["portfolio_value_base"], 70)
        self.assertEqual(captured["by_asset_class"], {"stocks": 70})
        self.portfolio.unlink()
        self.fx.unlink()
        with zipfile.ZipFile(self.bundle) as archive:
            manifest = json.loads(archive.read("rikdom-export.json"))
            run = json.loads(archive.read("analysis/run.json"))
        self.assertEqual(manifest["format_version"], "3.0.0")
        self.assertEqual(run["parameters"]["fx_lock"]["rates_to_base"], {"USD": 5})
        self.assertEqual(run["method"], {"name": "aggregate", "version": "1.0.0"})
        self.assertTrue(run["environment"]["core_sha256"])
        self.assertEqual(run["environment"].get("plugins"), [])
        self.assertTrue(run["dependency_lock"]["sha256"])
        restored = self.root / "restored"
        env = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
        script = (
            "import socket, sys\n"
            "def denied(*args, **kwargs):\n"
            "    raise AssertionError('Network forbidden during replay')\n"
            "socket.socket = denied\n"
            "socket.create_connection = denied\n"
            "from rikdom.cli import main\n"
            "sys.exit(main(sys.argv[1:]))\n"
        )
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                "replay-export",
                "--bundle",
                str(self.bundle),
                "--restore-dir",
                str(restored),
            ],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual((process.returncode, process.stderr), (0, ""))
        replayed = json.loads(process.stdout)
        self.assertEqual(replayed["status"], "reproduced")
        self.assertEqual(replayed["result"], captured)
        self.assertEqual(
            json.loads((restored / "analysis/result.json").read_text()), captured
        )
        self.assertEqual(
            len(json.loads((restored / "data/portfolio.json").read_text())["holdings"]),
            2,
        )
        self.assertTrue((restored / "environment/uv.lock").is_file())
        self.assertEqual(run_cli(["verify-export", "--bundle", str(self.bundle)])[0], 0)

    def test_capture_uses_actual_inputs_even_if_workspace_changes(self) -> None:
        from rikdom.analysis_bundle import capture_aggregate_bundle

        def mutate_source(*args, **kwargs):
            self.portfolio.write_text('{"changed": true}')
            return capture_aggregate_bundle(*args, **kwargs)

        with patch("rikdom.cli.capture_aggregate_bundle", side_effect=mutate_source):
            self.assertEqual(self.capture()[0], 0)
        code, stdout, stderr = self.replay()
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["result"]["portfolio_value_base"], 70)

    def test_legacy_compact_v3_result_still_replays(self) -> None:
        self.assertEqual(self.capture()[0], 0)
        # Frozen aggregate/1.0.0 result shape, predating optional CLI evidence.
        expected = {
            "base_currency": "BRL",
            "portfolio_value_base": 70,
            "by_asset_class": {"stocks": 70},
            "warnings": [],
            "errors": [],
            "by_region": {"__unclassified__": 70},
            "by_currency": {"BRL": 20, "USD": 50},
            "by_duration": {"__unclassified__": 70},
            "by_liquidity_tier": {"__unclassified__": 70},
            "by_account": {"__unassigned__": 70},
        }

        def freeze_legacy_result(payloads):
            result_bytes = json.dumps(expected).encode()
            payloads["analysis/result.json"] = result_bytes
            run = json.loads(payloads["analysis/run.json"])
            run["result"]["sha256"] = hashlib.sha256(result_bytes).hexdigest()
            payloads["analysis/run.json"] = json.dumps(run).encode()

        self.rewrite(freeze_legacy_result)
        code, stdout, stderr = self.replay()
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["result"], expected)

    def test_replay_rejects_corruption_before_creating_destination(self) -> None:
        self.assertEqual(self.capture()[0], 0)
        with zipfile.ZipFile(self.bundle) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        contents["data/portfolio.json"] += b"\n"
        with zipfile.ZipFile(self.bundle, "w") as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        code, _, stderr = self.replay()
        self.assertEqual(code, 1)
        self.assertIn("mismatch", stderr)
        self.assertFalse((self.root / "restored").exists())

    def test_replay_rejects_unsupported_method_environment_and_missing_lock(
        self,
    ) -> None:
        for field, value, message in (
            ("method", {"name": "shell", "version": "1"}, "Unsupported calculation"),
            ("format_version", "99.0.0", "Unsupported analysis run"),
            ("environment", {}, "Incompatible runtime"),
            ("parameters", {"strict": "false"}, "Invalid aggregate parameters"),
            (
                "equality",
                {"absolute_tolerance": 999999},
                "Unsupported financial equality",
            ),
            ("inputs", {}, "reference mismatch"),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.capture()[0], 0)
                self.change_run(field, value)
                code, _, stderr = self.replay()
                self.assertEqual(code, 1)
                self.assertIn(message, stderr)
                self.assertFalse((self.root / "restored").exists())
        self.assertEqual(self.capture()[0], 0)
        self.rewrite(lambda payloads: payloads.pop("environment/uv.lock"))
        code, _, stderr = self.replay()
        self.assertEqual(code, 1)
        self.assertIn("Missing dependency lock", stderr)
        self.assertFalse((self.root / "restored").exists())

    def test_replay_detects_changed_financial_result_even_with_valid_hashes(
        self,
    ) -> None:
        self.assertEqual(self.capture()[0], 0)

        def mutate(payloads):
            result = json.loads(payloads["analysis/result.json"])
            result["portfolio_value_base"] = 71
            data = json.dumps(result).encode()
            payloads["analysis/result.json"] = data
            run = json.loads(payloads["analysis/run.json"])
            run["result"]["sha256"] = hashlib.sha256(data).hexdigest()
            payloads["analysis/run.json"] = json.dumps(run).encode()

        self.rewrite(mutate)
        code, _, stderr = self.replay()
        self.assertEqual(code, 1)
        self.assertIn("financial result does not match", stderr)
        self.assertFalse((self.root / "restored").exists())

    def test_replay_rejects_incomplete_or_inconsistent_fx_evidence(self) -> None:
        for index, change in enumerate(
            (
                {"base_currency": "USD"},
                {"snapshot_timestamp": "not-a-timestamp"},
                {"snapshot_timestamp": "2026-01-01"},
                {"rate_dates": {}},
                {"sources": {}},
                {"rate_dates": {"USD": "2099-01-01"}},
                {"rates_to_base": {"USD": True}},
                {"rates_to_base": {"USD": -5}},
                {"rates_to_base": {"USD": float("inf")}},
                {"sources": {"USD": ""}},
                {"unexpected": True},
            )
        ):
            with self.subTest(change=change):
                self.assertEqual(self.capture()[0], 0)
                with zipfile.ZipFile(self.bundle) as archive:
                    parameters = json.loads(archive.read("analysis/run.json"))[
                        "parameters"
                    ]
                parameters["fx_lock"].update(change)
                self.change_run("parameters", parameters)
                target = self.root / f"restored-{index}"
                code, _, stderr = self.replay(target)
                self.assertEqual(code, 1)
                self.assertIn("Invalid aggregate FX lock", stderr)
                self.assertFalse(target.exists())
        self.assertEqual(self.capture()[0], 0)
        with zipfile.ZipFile(self.bundle) as archive:
            parameters = json.loads(archive.read("analysis/run.json"))["parameters"]
        parameters["fx_lock"] = {"rates_to_base": {"USD": 5}}
        self.change_run("parameters", parameters)
        code, _, stderr = self.replay()
        self.assertEqual(code, 1)
        self.assertIn("Invalid aggregate FX lock", stderr)
        self.assertFalse((self.root / "restored").exists())

    def test_replay_preserves_existing_directory(self) -> None:
        self.assertEqual(self.capture()[0], 0)
        target = self.root / "restored"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("keep")
        code, _, stderr = self.replay(target)
        self.assertEqual(code, 1)
        self.assertIn("must not exist", stderr)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(list(target.iterdir()), [sentinel])

    def test_restore_write_failure_leaves_no_partial_workspace(self) -> None:
        self.assertEqual(self.capture()[0], 0)
        write_bytes = Path.write_bytes

        def fail(path, data):
            if path.name == "result.json":
                raise OSError("interrupted write")
            return write_bytes(path, data)

        with patch.object(Path, "write_bytes", fail):
            code, _, stderr = self.replay()
        self.assertEqual(code, 1)
        self.assertIn("interrupted write", stderr)
        self.assertFalse((self.root / "restored").exists())
        self.assertEqual(list(self.root.glob(".rikdom-restore-*")), [])

    def test_capture_preserves_partial_data_warnings_and_refuses_strict_failure(
        self,
    ) -> None:
        self.fx.unlink()
        code, stdout, stderr = self.capture()
        self.assertEqual((code, stderr), (0, ""))
        partial = json.loads(stdout)
        self.assertEqual(partial["portfolio_value_base"], 20)
        self.assertTrue(partial["warnings"])
        code, stdout, stderr = self.replay()
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["result"], partial)
        self.bundle.unlink()
        code, _, stderr = self.capture("--strict-quality")
        self.assertEqual(code, 1)
        self.assertIn("strict mode", stderr)
        self.assertFalse(self.bundle.exists())

    def test_capture_cannot_overwrite_portfolio_or_fx_input(self) -> None:
        for path in (self.portfolio, self.fx):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                self.bundle = path
                code, _, stderr = self.capture()
                self.assertEqual(code, 1)
                self.assertIn("Refusing to overwrite", stderr)
                self.assertEqual(path.read_bytes(), original)

    def test_v3_requires_analysis_restore_instead_of_silently_discarding_run(
        self,
    ) -> None:
        self.assertEqual(self.capture()[0], 0)
        target = self.root / "target" / "portfolio.json"
        code, _, stderr = run_cli(
            ["import-export", "--bundle", str(self.bundle), "--portfolio", str(target)]
        )
        self.assertEqual(code, 1)
        self.assertIn("replay-export", stderr)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
