from __future__ import annotations

from pathlib import Path

from .manifest import PluginManifest, load_manifest


def discover_plugins(plugins_dir: str | Path) -> list[PluginManifest]:
    root = Path(plugins_dir)
    if not root.exists():
        return []

    manifests: list[PluginManifest] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "plugin.json"
        if not manifest_path.exists():
            continue
        manifests.append(load_manifest(child))
    return manifests


def plugin_index(plugins_dir: str | Path) -> dict[str, PluginManifest]:
    return {manifest.name: manifest for manifest in discover_plugins(plugins_dir)}

