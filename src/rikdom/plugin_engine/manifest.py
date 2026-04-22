from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files as resource_files
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from .errors import PluginManifestError

_MANIFEST_SCHEMA_RESOURCE = "plugin.manifest.schema.json"


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


def _load_manifest_schema_text() -> str:
    """Read the plugin manifest schema from bundled package resources."""
    resource = resource_files("rikdom._resources").joinpath(_MANIFEST_SCHEMA_RESOURCE)
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise PluginManifestError(
            f"Unable to load bundled plugin manifest schema "
            f"({_MANIFEST_SCHEMA_RESOURCE}) from rikdom._resources"
        ) from exc


@lru_cache(maxsize=1)
def _manifest_validator() -> Draft202012Validator:
    raw = _load_manifest_schema_text()
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise PluginManifestError(
            "Invalid JSON in bundled plugin manifest schema"
        ) from exc
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_against_schema(raw: Any, manifest_path: Path) -> None:
    validator = _manifest_validator()
    try:
        validator.validate(raw)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise PluginManifestError(
            f"Invalid plugin manifest {manifest_path}: {exc.message} (at {location})"
        ) from exc


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

    _validate_against_schema(raw, manifest_path)

    # Schema has already enforced presence, types, and non-empty constraints
    # for all required fields. The extraction below is straightforward.
    name = str(raw["name"]).strip()
    version = str(raw["version"]).strip()
    api_version = str(raw["api_version"]).strip()
    plugin_types = [str(v) for v in raw["plugin_types"]]
    module = str(raw["module"]).strip()
    class_name = str(raw["class_name"]).strip()
    description = str(raw.get("description", "")).strip()

    return PluginManifest(
        name=name,
        version=version,
        api_version=api_version,
        plugin_types=plugin_types,
        module=module,
        class_name=class_name,
        description=description,
        path=plugin_dir,
    )
