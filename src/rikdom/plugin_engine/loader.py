from __future__ import annotations

from pathlib import Path

from .manifest import PluginManifest, load_manifest


def discover_plugins(plugins_dir: str | Path) -> list[PluginManifest]:
    manifests, _warnings = discover_plugins_with_warnings(plugins_dir, strict=True)
    return manifests


def discover_plugins_with_warnings(
    plugins_dir: str | Path, *, strict: bool = False
) -> tuple[list[PluginManifest], list[str]]:
    root = Path(plugins_dir)
    if not root.exists():
        return [], []

    manifests: list[PluginManifest] = []
    warnings: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "plugin.json"
        if not manifest_path.exists():
            continue
        try:
            manifests.append(load_manifest(child))
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            warnings.append(
                f"Skipping plugin directory '{child.name}': failed to load manifest ({exc})"
            )
    return manifests, warnings


def plugin_index(plugins_dir: str | Path) -> dict[str, PluginManifest]:
    return {manifest.name: manifest for manifest in discover_plugins(plugins_dir)}

