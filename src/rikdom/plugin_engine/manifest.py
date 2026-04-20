from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PluginManifestError


@dataclass(slots=True)
class PluginManifest:
    name: str
    version: str
    api_version: str
    plugin_types: list[str]
    module: str
    class_name: str
    description: str
    path: Path


def _as_str_list(value: Any, field_name: str, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise PluginManifestError(f"plugin.json field '{field_name}' is required")
        return []
    if not isinstance(value, list):
        raise PluginManifestError(f"plugin.json field '{field_name}' must be an array")
    return [str(v) for v in value]


def load_manifest(plugin_dir: Path) -> PluginManifest:
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        raise PluginManifestError(f"Missing plugin manifest: {manifest_path}")

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PluginManifestError(f"Invalid JSON in manifest: {manifest_path}") from exc

    if not isinstance(raw, dict):
        raise PluginManifestError(f"Manifest must be an object: {manifest_path}")

    name = str(raw.get("name", "")).strip()
    version = str(raw.get("version", "")).strip()
    if not name:
        raise PluginManifestError(f"Manifest missing required field 'name': {manifest_path}")
    if not version:
        raise PluginManifestError(f"Manifest missing required field 'version': {manifest_path}")

    api_version = str(raw.get("api_version", "1.0")).strip() or "1.0"
    plugin_types = _as_str_list(raw.get("plugin_types"), "plugin_types", required=True)
    if not plugin_types:
        raise PluginManifestError(f"plugin.json field 'plugin_types' must not be empty: {manifest_path}")
    module = raw.get("module")
    class_name = raw.get("class_name")
    if not isinstance(module, str) or not module.strip():
        raise PluginManifestError(f"plugin.json field 'module' must be a non-empty string: {manifest_path}")
    if not isinstance(class_name, str) or not class_name.strip():
        raise PluginManifestError(
            f"plugin.json field 'class_name' must be a non-empty string: {manifest_path}"
        )

    description = str(raw.get("description", "")).strip()
    return PluginManifest(
        name=name,
        version=version,
        api_version=api_version,
        plugin_types=plugin_types,
        module=module.strip(),
        class_name=class_name.strip(),
        description=description,
        path=plugin_dir,
    )
