from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rikdom.cli import main
from rikdom.plugin_engine.loader import discover_plugins
from rikdom.plugin_engine.manifest import load_manifest


def _run(args: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class PluginInitCliTests(unittest.TestCase):
    def test_creates_expected_files_with_substitutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "plugins"
            code, stdout, stderr = _run(
                [
                    "plugin",
                    "init",
                    "my-new-plugin",
                    "--dest",
                    str(dest),
                    "--description",
                    "my fancy importer",
                ]
            )
            self.assertEqual(code, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["name"], "my-new-plugin")
            self.assertTrue(payload["created"].endswith("my-new-plugin"))

            plugin_dir = dest / "my-new-plugin"
            for rel in (
                "plugin.json",
                "plugin.py",
                "fixtures/sample.csv",
                "tests/test_plugin.py",
                "README.md",
            ):
                self.assertTrue(
                    (plugin_dir / rel).exists(), f"missing generated file: {rel}"
                )
            # .template suffix must not be present anywhere.
            for leftover in plugin_dir.rglob("*.template"):
                self.fail(f"unexpected .template file: {leftover}")

            manifest_raw = json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest_raw["name"], "my-new-plugin")
            self.assertEqual(manifest_raw["description"], "my fancy importer")
            self.assertEqual(manifest_raw["api_version"], "1.0")

            plugin_py = (plugin_dir / "plugin.py").read_text(encoding="utf-8")
            self.assertIn("my-new-plugin", plugin_py)
            self.assertNotIn("{{plugin_name}}", plugin_py)

            # load_manifest validates against the schema.
            manifest = load_manifest(plugin_dir)
            self.assertEqual(manifest.name, "my-new-plugin")
            self.assertEqual(manifest.api_version, "1.0")
            self.assertEqual(manifest.plugin_types, ["source/input"])

    def test_discover_plugins_finds_generated_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "plugins"
            code, _, stderr = _run(
                ["plugin", "init", "demo-plugin", "--dest", str(dest)]
            )
            self.assertEqual(code, 0, stderr)

            discovered = discover_plugins(dest)
            self.assertEqual(len(discovered), 1)
            manifest = discovered[0]
            self.assertEqual(manifest.name, "demo-plugin")
            self.assertEqual(manifest.api_version, "1.0")
            self.assertEqual(manifest.module, "plugin")
            self.assertEqual(manifest.class_name, "Plugin")
            self.assertEqual(manifest.description, "TODO: describe this plugin")

    def test_rejects_invalid_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "plugins"
            for bad in (
                "BadName",
                "1starts-with-digit",
                "a",  # too short (under 2)
                "has_underscore",
                "with/slash",
                "with space",
            ):
                with self.subTest(name=bad):
                    code, _, stderr = _run(
                        ["plugin", "init", bad, "--dest", str(dest)]
                    )
                    self.assertEqual(code, 1, f"expected failure for {bad!r}: {stderr}")
                    self.assertIn("Invalid plugin name", stderr)
                    self.assertFalse((dest / bad).exists())

    def test_refuses_to_overwrite_existing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "plugins"
            code, _, stderr = _run(
                ["plugin", "init", "demo-plugin", "--dest", str(dest)]
            )
            self.assertEqual(code, 0, stderr)

            code, _, stderr = _run(
                ["plugin", "init", "demo-plugin", "--dest", str(dest)]
            )
            self.assertEqual(code, 1)
            self.assertIn("existing plugin directory", stderr)

    def test_description_with_special_chars_is_json_escaped(self) -> None:
        tricky = 'Parse broker "statements"\nwith\\backslashes'
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "plugins"
            code, _, stderr = _run(
                [
                    "plugin",
                    "init",
                    "quoted-plugin",
                    "--dest",
                    str(dest),
                    "--description",
                    tricky,
                ]
            )
            self.assertEqual(code, 0, stderr)

            plugin_dir = dest / "quoted-plugin"
            manifest_raw = (plugin_dir / "plugin.json").read_text(encoding="utf-8")
            manifest = json.loads(manifest_raw)
            self.assertEqual(manifest["description"], tricky)

            loaded = load_manifest(plugin_dir)
            self.assertEqual(loaded.description, tricky)

    def test_generated_test_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "plugins"
            code, _, stderr = _run(
                ["plugin", "init", "demo-plugin", "--dest", str(dest)]
            )
            self.assertEqual(code, 0, stderr)

            plugin_dir = dest / "demo-plugin"
            # Run the generated test via subprocess so sys.path and cwd match
            # the "author runs it from the plugin dir" scenario.
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "tests.test_plugin", "-v"],
                cwd=plugin_dir,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"generated test failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
