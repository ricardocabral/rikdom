from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .contracts import OutputRequest, PhaseName, PluginContext
from .errors import PluginEngineError, PluginLoadError, PluginTypeError
from .loader import discover_plugins_with_warnings, plugin_index
from .runtime import build_manager, load_plugin_instance


def _new_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _load_single_plugin_manager(
    plugin_name: str,
    plugins_dir: str | Path,
    expected_type: str | None = None,
):
    manifests = plugin_index(plugins_dir)
    if plugin_name not in manifests:
        raise PluginLoadError(f"Plugin '{plugin_name}' not found in {plugins_dir}")

    manifest = manifests[plugin_name]
    if expected_type and expected_type not in manifest.plugin_types:
        raise PluginTypeError(
            f"Plugin '{plugin_name}' does not support plugin type '{expected_type}'"
        )

    plugin_dir = Path(plugins_dir) / plugin_name
    pm = build_manager()
    plugin_obj = load_plugin_instance(plugin_dir, manifest)
    pm.register(plugin_obj, name=manifest.name)
    return pm, manifest


def run_import_pipeline(plugin_name: str, plugins_dir: str, input_path: str) -> dict:
    pm, _ = _load_single_plugin_manager(
        plugin_name=plugin_name,
        plugins_dir=plugins_dir,
        expected_type=PhaseName.SOURCE_INPUT,
    )
    ctx = PluginContext(run_id=_new_run_id("import"), plugin_name=plugin_name)
    result = pm.hook.source_input(ctx=ctx, input_path=input_path)
    if not isinstance(result, dict):
        raise PluginEngineError("source/input plugin must return an object")
    return result


def run_output_pipeline(
    plugin_name: str,
    plugins_dir: str,
    portfolio_path: str,
    snapshots_path: str,
    output_dir: str,
) -> dict:
    pm, _ = _load_single_plugin_manager(
        plugin_name=plugin_name,
        plugins_dir=plugins_dir,
        expected_type=PhaseName.OUTPUT,
    )
    ctx = PluginContext(run_id=_new_run_id("output"), plugin_name=plugin_name)
    request = OutputRequest(
        portfolio_path=portfolio_path,
        snapshots_path=snapshots_path,
        output_dir=output_dir,
    )
    result = pm.hook.output(ctx=ctx, request=request)
    if not isinstance(result, dict):
        raise PluginEngineError("output plugin must return an object")
    return result


def run_storage_sync_pipeline(
    plugin_name: str,
    plugins_dir: str,
    portfolio_path: str,
    snapshots_path: str,
    options: dict | None = None,
) -> dict:
    pm, _ = _load_single_plugin_manager(
        plugin_name=plugin_name,
        plugins_dir=plugins_dir,
        expected_type=PhaseName.STATE_STORAGE,
    )
    ctx = PluginContext(run_id=_new_run_id("storage-sync"), plugin_name=plugin_name)
    result = pm.hook.state_storage_sync(
        ctx=ctx,
        portfolio_path=portfolio_path,
        snapshots_path=snapshots_path,
        options=options or {},
    )
    if not isinstance(result, dict):
        raise PluginEngineError("state/storage sync plugin must return an object")
    return result


def run_storage_health_pipeline(
    plugin_name: str,
    plugins_dir: str,
    options: dict | None = None,
) -> dict:
    pm, _ = _load_single_plugin_manager(
        plugin_name=plugin_name,
        plugins_dir=plugins_dir,
        expected_type=PhaseName.STATE_STORAGE,
    )
    ctx = PluginContext(run_id=_new_run_id("storage-health"), plugin_name=plugin_name)
    result = pm.hook.state_storage_health(ctx=ctx, options=options or {})
    if not isinstance(result, dict):
        raise PluginEngineError("state/storage health plugin must return an object")
    return result


def build_asset_type_catalog_with_warnings(plugins_dir: str | Path) -> tuple[list[dict], list[str]]:
    ctx = PluginContext(run_id=_new_run_id("asset-catalog"), plugin_name="catalog")

    merged: list[dict] = []
    seen: set[str] = set()
    warnings: list[str] = []

    try:
        manifests, discovery_warnings = discover_plugins_with_warnings(plugins_dir)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Asset type catalog discovery failed: {exc}")
        return merged, warnings
    warnings.extend(discovery_warnings)

    for manifest in manifests:
        if PhaseName.ASSET_TYPE_CATALOG not in manifest.plugin_types:
            continue
        if not manifest.module or not manifest.class_name:
            warnings.append(
                f"Skipping catalog plugin '{manifest.name}': missing module/class_name in manifest"
            )
            continue

        try:
            plugin_obj = load_plugin_instance(Path(plugins_dir) / manifest.name, manifest)
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"Skipping catalog plugin '{manifest.name}': failed to load ({exc})"
            )
            continue

        hook = getattr(plugin_obj, "asset_type_catalog", None)
        if not callable(hook):
            warnings.append(
                f"Skipping catalog plugin '{manifest.name}': missing asset_type_catalog hook"
            )
            continue

        try:
            chunk = hook(ctx=ctx)
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"Skipping catalog plugin '{manifest.name}': hook error ({exc})"
            )
            continue

        if not isinstance(chunk, list):
            warnings.append(
                f"Skipping catalog plugin '{manifest.name}': hook returned non-list payload"
            )
            continue

        for item in chunk:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "")).strip()
            if not item_id or item_id in seen:
                continue
            merged.append(item)
            seen.add(item_id)

    return merged, warnings


def build_asset_type_catalog(plugins_dir: str | Path) -> list[dict]:
    catalog, _warnings = build_asset_type_catalog_with_warnings(plugins_dir)
    return catalog

