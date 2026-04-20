from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pluggy

from .errors import PluginLoadError
from .hookspecs import RikdomHookSpecs
from .manifest import PluginManifest


def build_manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager("rikdom")
    pm.add_hookspecs(RikdomHookSpecs)
    return pm


def load_plugin_instance(plugin_dir: Path, manifest: PluginManifest):
    if not manifest.module or not manifest.class_name:
        raise PluginLoadError(
            f"Plugin '{manifest.name}' must declare 'module' and 'class_name' for Pluggy execution"
        )

    module_path = plugin_dir / f"{manifest.module}.py"
    if not module_path.exists():
        raise PluginLoadError(
            f"Plugin '{manifest.name}' module file not found: {module_path}"
        )

    module_name = f"rikdom_plugin_{manifest.name.replace('-', '_')}_{manifest.module}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(
            f"Cannot build import spec for plugin '{manifest.name}': {module_path}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(plugin_dir))
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise PluginLoadError(
            f"Failed loading plugin module '{manifest.name}': {exc}"
        ) from exc
    finally:
        if sys.path and sys.path[0] == str(plugin_dir):
            sys.path.pop(0)

    try:
        cls = getattr(module, manifest.class_name)
    except AttributeError as exc:
        raise PluginLoadError(
            f"Plugin '{manifest.name}' class not found: {manifest.class_name}"
        ) from exc

    try:
        return cls()
    except Exception as exc:  # noqa: BLE001
        raise PluginLoadError(
            f"Plugin '{manifest.name}' failed to instantiate: {exc}"
        ) from exc

