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
    "api_version": "1.0",
    "plugin_types": ["source/input"],
    "module": "sample.module",
    "class_name": "SamplePlugin",
}


def _write_manifest(tmp: Path, payload: dict) -> Path:
    plugin_dir = tmp / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    return plugin_dir


class LoadManifestSchemaTest(unittest.TestCase):
    def test_valid_manifest_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), dict(BASE_MANIFEST))
            manifest = load_manifest(plugin_dir)
        self.assertEqual(manifest.name, "sample-plugin")
        self.assertEqual(manifest.api_version, "1.0")
        self.assertEqual(manifest.plugin_types, ["source/input"])
        self.assertEqual(manifest.module, "sample.module")
        self.assertEqual(manifest.class_name, "SamplePlugin")
        self.assertIsNone(manifest.command)

    def test_missing_api_version_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload.pop("api_version")
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError) as ctx:
                load_manifest(plugin_dir)
        self.assertIn("api_version", str(ctx.exception))

    def test_unknown_api_version_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["api_version"] = "2.0"
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_blank_api_version_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["api_version"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_empty_plugin_types_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["plugin_types"] = []
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_missing_module_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload.pop("module")
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError) as ctx:
                load_manifest(plugin_dir)
        self.assertIn("module", str(ctx.exception))

    def test_missing_class_name_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload.pop("class_name")
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_empty_name_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["name"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_additional_properties_rejected(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["rogue_field"] = "nope"
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            with self.assertRaises(PluginManifestError):
                load_manifest(plugin_dir)

    def test_optional_description_allowed(self) -> None:
        payload = dict(BASE_MANIFEST)
        payload["description"] = "A sample plugin"
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_manifest(Path(tmp), payload)
            manifest = load_manifest(plugin_dir)
        self.assertEqual(manifest.description, "A sample plugin")


if __name__ == "__main__":
    unittest.main()
