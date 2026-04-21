from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rikdom.plugin_engine.errors import PluginManifestError
from rikdom.plugin_engine.manifest import load_manifest


BASE_MANIFEST: dict = {
    "name": "sample-plugin",
    "version": "0.1.0",
    "plugin_types": ["source_input"],
    "module": "sample.module",
    "class_name": "SamplePlugin",
}


def _write_manifest(tmp: Path, payload: dict) -> Path:
    plugin_dir = tmp / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    return plugin_dir


class LoadManifestCommandTest(unittest.TestCase):
    def test_command_absent_yields_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), dict(BASE_MANIFEST))
            manifest = load_manifest(plugin_dir)
            self.assertIsNone(manifest.command)

    def test_command_list_of_strings_loads(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["command"] = ["python", "foo.py"]
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            manifest = load_manifest(plugin_dir)
            self.assertEqual(manifest.command, ["python", "foo.py"])

    def test_command_non_list_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["command"] = "not-a-list"
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_command_empty_list_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["command"] = []
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_command_non_string_entries_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["command"] = ["python", 3]
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)


if __name__ == "__main__":
    unittest.main()
