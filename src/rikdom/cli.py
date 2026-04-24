from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from importlib.resources import as_file, files as resource_files
from pathlib import Path
from typing import Any

from .aggregate import aggregate_portfolio
from .fx import ensure_snapshot_fx_lock
from .journal import (
    DEFAULT_POLICY,
    DEFAULT_ROTATE_BYTES,
    CompactionPolicy,
    compact_snapshots,
    rotate_journal,
    verify_journal,
)
from .migrations import (
    MigrationPlanError,
    apply_migrations,
    format_version,
    parse_version,
    plan_migrations,
)
from .plugin_engine.errors import PluginEngineError
from .plugin_engine.loader import discover_plugins
from .plugin_engine.pipeline import (
    build_asset_type_catalog_with_warnings,
    run_import_pipeline,
    run_output_pipeline,
    run_storage_sync_pipeline,
)
from .import_preflight import build_preflight_report
from .plugins import (
    MergeCounts,
    build_import_diff,
    merge_activities,
    merge_holdings,
    stamp_provenance,
)
from .snapshot import snapshot_from_aggregate
from .storage import append_jsonl, load_json, load_jsonl, save_json
from .validate import CURRENT_SCHEMA_VERSION, validate_portfolio


DEFAULT_DATA_DIR = "data"
DEFAULT_OUT_ROOT = "out"

DEFAULT_PORTFOLIO_PATH = f"{DEFAULT_DATA_DIR}/portfolio.json"
DEFAULT_SNAPSHOTS_PATH = f"{DEFAULT_DATA_DIR}/snapshots.jsonl"
DEFAULT_FX_HISTORY_PATH = f"{DEFAULT_DATA_DIR}/fx_rates.jsonl"
DEFAULT_IMPORT_LOG = f"{DEFAULT_DATA_DIR}/import_log.jsonl"
DEFAULT_REGISTRY_PATH = f"{DEFAULT_DATA_DIR}/portfolio_registry.json"

SAMPLE_PORTFOLIO_PATH = "data-sample/portfolio.json"
SAMPLE_SNAPSHOTS_PATH = "data-sample/snapshots.jsonl"
SAMPLE_FX_HISTORY_PATH = "data-sample/fx_rates.jsonl"
DEFAULT_WORKSPACE_PORTFOLIOS = ("main", "paper", "retirement")

_PORTFOLIO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def _validate_portfolio_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("Portfolio name must be a non-empty string")
    if (
        not _PORTFOLIO_NAME_PATTERN.fullmatch(name)
        or ".." in name
        or "/" in name
        or "\\" in name
    ):
        raise ValueError(
            f"Invalid portfolio name '{name}': must not contain path separators, "
            "'..', or leading dots/dashes"
        )
    return name


def _now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _default_workspace_paths(data_dir: str, out_root: str) -> dict[str, str]:
    data_root = Path(data_dir)
    out_path = Path(out_root)
    return {
        "portfolio": str(data_root / "portfolio.json"),
        "snapshots": str(data_root / "snapshots.jsonl"),
        "fx_history": str(data_root / "fx_rates.jsonl"),
        "import_log": str(data_root / "import_log.jsonl"),
        "registry": str(data_root / "portfolio_registry.json"),
        "out": str(out_path / "dashboard.html"),
        "out_dir": str(out_path / "reports"),
        "db_path": str(out_path / "rikdom.duckdb"),
    }


def _portfolio_workspace_paths(
    portfolio_name: str, data_dir: str, out_root: str
) -> dict[str, str]:
    _validate_portfolio_name(portfolio_name)
    scoped_data = Path(data_dir) / "portfolios" / portfolio_name
    scoped_out = Path(out_root) / portfolio_name
    return {
        "portfolio": str(scoped_data / "portfolio.json"),
        "snapshots": str(scoped_data / "snapshots.jsonl"),
        "fx_history": str(scoped_data / "fx_rates.jsonl"),
        "import_log": str(scoped_data / "import_log.jsonl"),
        "out": str(scoped_out / "dashboard.html"),
        "out_dir": str(Path(out_root) / "reports" / portfolio_name),
        "db_path": str(scoped_out / "rikdom.duckdb"),
    }


def _parse_csv_names(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _registry_entries(registry_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    raw_entries = registry_payload.get("portfolios")
    if not isinstance(raw_entries, list):
        return entries
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            entries[name] = item
    return entries


def _load_portfolio_registry(registry_path: str) -> dict[str, Any]:
    payload = load_json(registry_path)
    if not isinstance(payload, dict):
        raise ValueError(
            f"Invalid registry format in {registry_path}: expected JSON object"
        )
    return payload


def _workspace_entry_for(registry_path: str, portfolio_name: str) -> dict[str, Any]:
    registry_payload = _load_portfolio_registry(registry_path)
    entries = _registry_entries(registry_payload)
    entry = entries.get(portfolio_name)
    if entry is None:
        known = ", ".join(sorted(entries.keys())) or "(none)"
        raise ValueError(
            f"Portfolio '{portfolio_name}' not found in registry {registry_path}. Known: {known}"
        )
    return entry


def _resolve_workspace_args(args: argparse.Namespace) -> None:
    data_dir = getattr(args, "data_dir", None) or DEFAULT_DATA_DIR
    out_root = getattr(args, "out_root", None) or DEFAULT_OUT_ROOT
    defaults = _default_workspace_paths(data_dir, out_root)

    if hasattr(args, "data_dir"):
        args.data_dir = data_dir
    if hasattr(args, "out_root"):
        args.out_root = out_root
    if hasattr(args, "registry") and getattr(args, "registry", None) is None:
        args.registry = defaults["registry"]

    selected_name = getattr(args, "portfolio_name", None)
    selected_defaults: dict[str, str] = {}
    if isinstance(selected_name, str) and selected_name:
        registry_path = getattr(args, "registry", defaults["registry"])
        entry = _workspace_entry_for(registry_path, selected_name)
        selected_defaults = _portfolio_workspace_paths(
            selected_name, data_dir, out_root
        )
        for key in ("portfolio", "snapshots", "fx_history", "import_log"):
            candidate = entry.get(key)
            if isinstance(candidate, str) and candidate.strip():
                selected_defaults[key] = candidate

    resolved_defaults = {**defaults, **selected_defaults}
    for field_name, field_value in resolved_defaults.items():
        if hasattr(args, field_name) and getattr(args, field_name) is None:
            setattr(args, field_name, field_value)


def _bootstrap_default_file(path: str, default_path: str, sample_path: str) -> None:
    if path != default_path:
        return
    _copy_if_missing(path, sample_path)


def _copy_if_missing(path: str, sample_path: str) -> bool:
    target = Path(path)
    if target.exists():
        return False

    sample = Path(sample_path)
    if not sample.exists():
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(sample.read_bytes())
    return True


def _bootstrap_default_workspace(args: argparse.Namespace) -> None:
    data_dir = getattr(args, "data_dir", DEFAULT_DATA_DIR)
    out_root = getattr(args, "out_root", DEFAULT_OUT_ROOT)
    defaults = _default_workspace_paths(data_dir, out_root)
    selected_name = getattr(args, "portfolio_name", None)
    if isinstance(selected_name, str) and selected_name:
        defaults = {
            **defaults,
            **_portfolio_workspace_paths(selected_name, data_dir, out_root),
        }

    portfolio_path = getattr(args, "portfolio", None)
    if isinstance(portfolio_path, str):
        _bootstrap_default_file(
            portfolio_path, defaults["portfolio"], SAMPLE_PORTFOLIO_PATH
        )

    snapshots_path = getattr(args, "snapshots", None)
    if isinstance(snapshots_path, str):
        _bootstrap_default_file(
            snapshots_path, defaults["snapshots"], SAMPLE_SNAPSHOTS_PATH
        )

    fx_history_path = getattr(args, "fx_history", None)
    if isinstance(fx_history_path, str):
        _bootstrap_default_file(
            fx_history_path, defaults["fx_history"], SAMPLE_FX_HISTORY_PATH
        )


def cmd_validate(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    errors = validate_portfolio(portfolio)
    if errors:
        print("Validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Portfolio structure is valid")
    return 0


def cmd_aggregate(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    aggregate_timestamp = _now_iso()
    fx_lock, fx_warnings = ensure_snapshot_fx_lock(
        portfolio,
        fx_history_path=args.fx_history,
        snapshot_timestamp=aggregate_timestamp,
        auto_ingest=False,
    )
    result = aggregate_portfolio(
        portfolio,
        strict=bool(getattr(args, "strict_quality", False)),
        fx_rates_to_base=fx_lock.get("rates_to_base"),
    )
    result.warnings.extend(fx_warnings)
    output = {
        "base_currency": result.base_currency,
        "portfolio_value_base": result.total_value_base,
        "by_asset_class": result.by_asset_class,
        "warnings": result.warnings,
        "errors": result.errors,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if result.errors:
        print("Data quality check failed in strict mode", file=sys.stderr)
        return 1
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    snapshot_timestamp = args.timestamp or _now_iso()
    fx_lock, fx_warnings = ensure_snapshot_fx_lock(
        portfolio,
        fx_history_path=args.fx_history,
        snapshot_timestamp=snapshot_timestamp,
        auto_ingest=not bool(args.no_fx_auto_ingest),
    )
    result = aggregate_portfolio(
        portfolio,
        strict=bool(getattr(args, "strict_quality", False)),
        fx_rates_to_base=fx_lock.get("rates_to_base"),
    )
    result.fx_lock = fx_lock
    result.warnings.extend(fx_warnings)
    if result.errors:
        print("Data quality check failed in strict mode:", file=sys.stderr)
        for err in result.errors:
            print(f"- {err}", file=sys.stderr)
        return 1
    snap = snapshot_from_aggregate(result, timestamp=snapshot_timestamp)
    rotate_bytes = getattr(args, "rotate_bytes", 0) or 0
    if rotate_bytes > 0:
        archived = rotate_journal(args.snapshots, max_bytes=rotate_bytes)
        if archived is not None:
            print(f"Rotated journal: {archived}")
    append_jsonl(args.snapshots, snap)
    print(f"Snapshot appended to {args.snapshots}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    return 0


def cmd_viz(args: argparse.Namespace) -> int:
    snapshots_path = args.snapshots
    temp_dir: TemporaryDirectory[str] | None = None

    if args.include_current:
        portfolio = load_json(args.portfolio)
        snapshots = load_jsonl(args.snapshots)
        current_timestamp = _now_iso()
        fx_lock, _fx_warnings = ensure_snapshot_fx_lock(
            portfolio,
            fx_history_path=args.fx_history,
            snapshot_timestamp=current_timestamp,
            auto_ingest=False,
        )
        aggregate = aggregate_portfolio(
            portfolio,
            fx_rates_to_base=fx_lock.get("rates_to_base"),
        )
        aggregate.fx_lock = fx_lock
        snapshots = snapshots + [snapshot_from_aggregate(aggregate)]

        temp_dir = TemporaryDirectory()
        temp_snapshots = Path(temp_dir.name) / "snapshots.with-current.jsonl"
        temp_snapshots.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in snapshots),
            encoding="utf-8",
        )
        snapshots_path = str(temp_snapshots)

    output_dir = str(Path(args.out).resolve().parent)
    try:
        payload = run_output_pipeline(
            plugin_name="quarto-portfolio-report",
            plugins_dir="plugins",
            portfolio_path=args.portfolio,
            snapshots_path=snapshots_path,
            output_dir=output_dir,
        )
    except PluginEngineError as exc:
        if temp_dir is not None:
            temp_dir.cleanup()
        print(f"Visualize failed: {exc}", file=sys.stderr)
        return 1

    if temp_dir is not None:
        temp_dir.cleanup()

    dashboard_artifact = next(
        (a for a in payload.get("artifacts", []) if a.get("type") == "html_dashboard"),
        None,
    )
    generated_dashboard = (
        Path(dashboard_artifact["path"])
        if dashboard_artifact and isinstance(dashboard_artifact.get("path"), str)
        else Path(output_dir) / "dashboard.html"
    )

    target_dashboard = Path(args.out).resolve()
    target_dashboard.parent.mkdir(parents=True, exist_ok=True)
    if generated_dashboard.resolve() != target_dashboard:
        shutil.copy2(generated_dashboard, target_dashboard)

    print(f"Dashboard written to {target_dashboard}")
    deep_dive = Path(output_dir) / "portfolio-report.html"
    if deep_dive.exists():
        print(f"Deep-dive report written to {deep_dive}")
    return 0


def _counts_dict(counts: MergeCounts) -> dict[str, int]:
    return {
        "inserted": counts.inserted,
        "updated": counts.updated,
        "skipped": counts.skipped,
    }


def _sync_asset_type_catalog_from_plugins(
    portfolio: dict[str, Any], plugins_dir: str
) -> dict[str, int]:
    existing = portfolio.get("asset_type_catalog")
    if not isinstance(existing, list):
        existing = []
        portfolio["asset_type_catalog"] = existing

    existing_ids: set[str] = set()
    for item in existing:
        if isinstance(item, dict):
            item_id = str(item.get("id", "")).strip()
            if item_id:
                existing_ids.add(item_id)

    try:
        discovered, warnings = build_asset_type_catalog_with_warnings(plugins_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: asset type catalog sync failed: {exc}", file=sys.stderr)
        return {"added": 0, "total": len(existing_ids)}
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    added = 0
    for item in discovered:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        if not item_id or item_id in existing_ids:
            continue
        existing.append(item)
        existing_ids.add(item_id)
        added += 1

    return {"added": added, "total": len(existing_ids)}


def cmd_import_statement(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    catalog_sync = _sync_asset_type_catalog_from_plugins(portfolio, args.plugins_dir)
    try:
        imported = run_import_pipeline(args.plugin, args.plugins_dir, args.input)
    except PluginEngineError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    import_run_id = args.import_run_id or f"run-{uuid.uuid4().hex[:16]}"
    ingested_at = args.ingested_at or _now_iso()
    source_system = imported.get("provider") or args.plugin

    stamp_provenance(
        imported,
        source_system=source_system,
        import_run_id=import_run_id,
        ingested_at=ingested_at,
    )

    preflight_report = build_preflight_report(portfolio, imported)
    dry_run_diff = build_import_diff(portfolio, imported)
    dry_run = bool(getattr(args, "dry_run", False))
    write_requested = bool(args.write)
    write_applied = write_requested and not dry_run

    if not preflight_report.get("ok", False):
        print(
            json.dumps(
                {
                    "import_run_id": import_run_id,
                    "ingested_at": ingested_at,
                    "source_system": source_system,
                    "plugin": args.plugin,
                    "input": args.input,
                    "preflight": preflight_report,
                    "dry_run_diff": dry_run_diff,
                    "write": False,
                    "write_requested": write_requested,
                    "dry_run": dry_run,
                    "catalog_sync": catalog_sync,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print(
            (
                "Import failed: preflight validation found "
                f"{preflight_report['summary']['blocking_issues']} blocking issue(s)"
            ),
            file=sys.stderr,
        )
        return 1

    try:
        merged, h_counts = merge_holdings(portfolio, imported)
        merged, a_counts = merge_activities(merged, imported)
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    if write_applied:
        save_json(args.portfolio, merged)

    log_entry = {
        "import_run_id": import_run_id,
        "ingested_at": ingested_at,
        "source_system": source_system,
        "plugin": args.plugin,
        "input": args.input,
        "preflight": preflight_report,
        "dry_run_diff": dry_run_diff,
        "holdings": _counts_dict(h_counts),
        "activities": _counts_dict(a_counts),
        "write": bool(write_applied),
        "write_requested": write_requested,
        "dry_run": dry_run,
        "catalog_sync": catalog_sync,
    }

    if args.import_log and write_applied:
        append_jsonl(args.import_log, log_entry)

    print(json.dumps(log_entry, indent=2, ensure_ascii=False))
    return 0


def cmd_imports_list(args: argparse.Namespace) -> int:
    entries = load_jsonl(args.import_log)
    if args.source_system:
        entries = [e for e in entries if e.get("source_system") == args.source_system]
    if args.import_run_id:
        entries = [e for e in entries if e.get("import_run_id") == args.import_run_id]
    if args.limit < 0:
        print("--limit must be a non-negative integer", file=sys.stderr)
        return 2
    if args.limit:
        entries = entries[-args.limit :]
    print(json.dumps({"imports": entries}, indent=2, ensure_ascii=False))
    return 0


def cmd_plugins_list(args: argparse.Namespace) -> int:
    manifests = discover_plugins(args.plugins_dir)
    payload = []
    for m in manifests:
        payload.append(
            {
                "name": m.name,
                "version": m.version,
                "api_version": m.api_version,
                "plugin_types": m.plugin_types,
                "module": m.module,
                "class_name": m.class_name,
                "description": m.description,
                "path": str(m.path),
            }
        )
    print(json.dumps({"plugins": payload}, indent=2, ensure_ascii=False))
    return 0


_PLUGIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


def _locate_sdk_template() -> Any:
    """Return the bundled ``template-plugin`` resource tree (a Traversable)."""
    root = resource_files("rikdom._resources").joinpath("template-plugin")
    if not root.is_dir():
        raise FileNotFoundError(
            "Bundled template-plugin resources are missing from rikdom._resources"
        )
    return root


def _render_template(text: str, substitutions: dict[str, str]) -> str:
    rendered = text
    for key, value in substitutions.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _render_manifest_template(text: str, substitutions: dict[str, str]) -> str:
    """Render ``plugin.json.template`` structurally.

    The manifest is parsed as JSON after a syntactic placeholder swap so that
    user-supplied values (name, description) are serialized with ``json.dumps``
    and cannot inject invalid JSON characters (quotes, backslashes, newlines).
    """
    sentinel_map: dict[str, str] = {}
    staged = text
    for key in substitutions:
        sentinel = f"__RIKDOM_TPL_{key.upper()}__"
        sentinel_map[sentinel] = substitutions[key]
        staged = staged.replace("{{" + key + "}}", sentinel)
    try:
        document = json.loads(staged)
    except json.JSONDecodeError as exc:
        raise ValueError(f"plugin.json template is not valid JSON: {exc}") from exc

    def _substitute(value: Any) -> Any:
        if isinstance(value, str):
            replaced = value
            for sentinel, actual in sentinel_map.items():
                replaced = replaced.replace(sentinel, actual)
            return replaced
        if isinstance(value, list):
            return [_substitute(item) for item in value]
        if isinstance(value, dict):
            return {k: _substitute(v) for k, v in value.items()}
        return value

    document = _substitute(document)
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _copy_template_tree(
    source: Any, destination: Path, substitutions: dict[str, str]
) -> list[Path]:
    created: list[Path] = []
    with as_file(source) as source_path:
        source_root = Path(source_path)
        for src_path in sorted(source_root.rglob("*")):
            rel = src_path.relative_to(source_root)
            target_rel_name = rel.name
            if target_rel_name.endswith(".template"):
                target_rel_name = target_rel_name[: -len(".template")]
            target = destination / rel.parent / target_rel_name
            if src_path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = src_path.read_text(encoding="utf-8")
            if target.name == "plugin.json":
                rendered = _render_manifest_template(raw, substitutions)
            else:
                rendered = _render_template(raw, substitutions)
            target.write_text(rendered, encoding="utf-8")
            created.append(target)
    return created


def cmd_plugin_init(args: argparse.Namespace) -> int:
    name = args.name
    if not isinstance(name, str) or not _PLUGIN_NAME_PATTERN.fullmatch(name):
        print(
            (
                f"Invalid plugin name '{name}': must match "
                "^[a-z][a-z0-9-]{1,63}$ (lowercase letter start, 2-64 chars, "
                "lowercase letters/digits/hyphens only)"
            ),
            file=sys.stderr,
        )
        return 1
    if "/" in name or "\\" in name or ".." in name:
        print(
            f"Invalid plugin name '{name}': path separators are not allowed",
            file=sys.stderr,
        )
        return 1

    dest_root = Path(args.dest)
    plugin_dir = dest_root / name
    if plugin_dir.exists():
        print(
            f"Refusing to overwrite existing plugin directory: {plugin_dir}",
            file=sys.stderr,
        )
        return 1

    try:
        template_root = _locate_sdk_template()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    description = args.description or "TODO: describe this plugin"
    substitutions = {
        "plugin_name": name,
        "plugin_description": description,
    }

    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        plugin_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(
            f"Failed to create plugin directory {plugin_dir}: {exc}",
            file=sys.stderr,
        )
        return 1
    try:
        _copy_template_tree(template_root, plugin_dir, substitutions)
    except Exception as exc:
        shutil.rmtree(plugin_dir, ignore_errors=True)
        print(f"Failed to scaffold plugin: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {"created": str(plugin_dir), "name": name},
            indent=2,
            ensure_ascii=False,
        )
    )
    print(
        (
            f"Scaffolded plugin '{name}' at {plugin_dir}. "
            f"Next: cd {plugin_dir} && uv run python -m unittest tests.test_plugin"
        ),
        file=sys.stderr,
    )
    return 0


def cmd_render_report(args: argparse.Namespace) -> int:
    try:
        payload = run_output_pipeline(
            plugin_name=args.plugin,
            plugins_dir=args.plugins_dir,
            portfolio_path=args.portfolio,
            snapshots_path=args.snapshots,
            output_dir=args.out_dir,
        )
    except PluginEngineError as exc:
        print(f"Render failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_storage_sync(args: argparse.Namespace) -> int:
    try:
        payload = run_storage_sync_pipeline(
            plugin_name=args.plugin,
            plugins_dir=args.plugins_dir,
            portfolio_path=args.portfolio,
            snapshots_path=args.snapshots,
            options={"db_path": args.db_path},
        )
    except PluginEngineError as exc:
        print(f"Storage sync failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_workspace_init(args: argparse.Namespace) -> int:
    names = (
        _parse_csv_names(args.portfolios)
        if args.portfolios
        else list(DEFAULT_WORKSPACE_PORTFOLIOS)
    )
    if not names:
        print("No portfolio names provided", file=sys.stderr)
        return 2
    try:
        for name in names:
            _validate_portfolio_name(name)
        _validate_portfolio_name(args.default_portfolio)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.default_portfolio not in names:
        print("--default-portfolio must be one of --portfolios", file=sys.stderr)
        return 2

    registry_path = Path(args.registry)
    if registry_path.exists() and not args.force:
        print(
            f"Registry already exists at {registry_path}. Pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    entries = []
    for name in names:
        scoped = _portfolio_workspace_paths(name, args.data_dir, args.out_root)
        entries.append(
            {
                "name": name,
                "portfolio": scoped["portfolio"],
                "snapshots": scoped["snapshots"],
                "fx_history": scoped["fx_history"],
                "import_log": scoped["import_log"],
            }
        )

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "default_portfolio": args.default_portfolio,
        "portfolios": entries,
    }
    save_json(registry_path, payload)

    seeded: list[str] = []
    if args.seed_sample:
        for entry in entries:
            seeded_portfolio = _copy_if_missing(
                entry["portfolio"], SAMPLE_PORTFOLIO_PATH
            )
            seeded_snapshots = _copy_if_missing(
                entry["snapshots"], SAMPLE_SNAPSHOTS_PATH
            )
            seeded_fx_history = _copy_if_missing(
                entry["fx_history"], SAMPLE_FX_HISTORY_PATH
            )
            if seeded_portfolio or seeded_snapshots or seeded_fx_history:
                seeded.append(entry["name"])

    print(
        json.dumps(
            {
                "status": "written",
                "registry": str(registry_path),
                "default_portfolio": args.default_portfolio,
                "portfolios": [e["name"] for e in entries],
                "seeded_from_sample": seeded,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_workspace_list(args: argparse.Namespace) -> int:
    payload = _load_portfolio_registry(args.registry)
    entries = _registry_entries(payload)
    listed = []
    for name in sorted(entries.keys()):
        entry = entries[name]
        portfolio = str(entry.get("portfolio", ""))
        snapshots = str(entry.get("snapshots", ""))
        import_log = str(entry.get("import_log", ""))
        fx_history = str(entry.get("fx_history", ""))
        listed.append(
            {
                "name": name,
                "portfolio": portfolio,
                "portfolio_exists": Path(portfolio).exists(),
                "snapshots": snapshots,
                "snapshots_exists": Path(snapshots).exists(),
                "fx_history": fx_history,
                "fx_history_exists": Path(fx_history).exists(),
                "import_log": import_log,
                "import_log_exists": Path(import_log).exists(),
            }
        )
    print(
        json.dumps(
            {
                "registry": args.registry,
                "default_portfolio": payload.get("default_portfolio"),
                "portfolios": listed,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _merge_by_asset_class(
    target: dict[str, float], increment: dict[str, float]
) -> None:
    for asset_class, amount in increment.items():
        target[asset_class] = round(target.get(asset_class, 0.0) + float(amount), 2)


def cmd_workspace_rollup(args: argparse.Namespace) -> int:
    payload = _load_portfolio_registry(args.registry)
    entries = _registry_entries(payload)
    requested = (
        _parse_csv_names(args.portfolios) if args.portfolios else sorted(entries.keys())
    )
    if not requested:
        print("No portfolios available in registry", file=sys.stderr)
        return 1

    per_portfolio = []
    warnings: list[str] = []
    totals_by_currency: dict[str, dict[str, Any]] = {}

    for name in requested:
        entry = entries.get(name)
        if entry is None:
            warnings.append(f"Portfolio '{name}' not found in registry")
            continue
        portfolio_path = entry.get("portfolio")
        if not isinstance(portfolio_path, str) or not portfolio_path.strip():
            warnings.append(f"Portfolio '{name}' has invalid 'portfolio' path")
            continue
        try:
            portfolio = load_json(portfolio_path)
        except FileNotFoundError:
            warnings.append(f"Portfolio file not found for '{name}': {portfolio_path}")
            continue

        fx_history_path = entry.get("fx_history")
        if not isinstance(fx_history_path, str) or not fx_history_path.strip():
            fx_history_path = str(Path(portfolio_path).with_name("fx_rates.jsonl"))
        fx_lock, fx_warnings = ensure_snapshot_fx_lock(
            portfolio,
            fx_history_path=fx_history_path,
            snapshot_timestamp=_now_iso(),
            auto_ingest=False,
        )
        aggregate = aggregate_portfolio(
            portfolio,
            fx_rates_to_base=fx_lock.get("rates_to_base"),
        )
        aggregate.warnings.extend(fx_warnings)
        per_portfolio.append(
            {
                "name": name,
                "portfolio": portfolio_path,
                "base_currency": aggregate.base_currency,
                "portfolio_value_base": aggregate.total_value_base,
                "by_asset_class": aggregate.by_asset_class,
                "warnings": aggregate.warnings,
            }
        )

        currency_bucket = totals_by_currency.setdefault(
            aggregate.base_currency,
            {"portfolio_value_base": 0.0, "by_asset_class": {}},
        )
        currency_bucket["portfolio_value_base"] = round(
            currency_bucket["portfolio_value_base"] + aggregate.total_value_base, 2
        )
        _merge_by_asset_class(
            currency_bucket["by_asset_class"], aggregate.by_asset_class
        )

    if not per_portfolio:
        print(
            json.dumps(
                {"status": "empty", "warnings": warnings}, indent=2, ensure_ascii=False
            )
        )
        return 1

    response: dict[str, Any] = {
        "registry": args.registry,
        "portfolios": per_portfolio,
        "warnings": warnings,
    }

    if len(totals_by_currency) == 1:
        base_currency = next(iter(totals_by_currency.keys()))
        response["base_currency"] = base_currency
        response["totals"] = totals_by_currency[base_currency]
    else:
        response["totals_by_currency"] = totals_by_currency
        response["warning"] = (
            "Multiple base currencies found; totals are grouped by currency."
        )

    print(json.dumps(response, indent=2, ensure_ascii=False))
    return 0


def _backup_path(portfolio_path: Path) -> Path:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return portfolio_path.with_name(f"{portfolio_path.name}.bak-{stamp}")


_SCHEMA_MISSING_KEYS = {"schema_version", "schema_uri"}


def _is_schema_only_precheck_error(err: str) -> bool:
    if err.startswith("Missing top-level keys: "):
        raw_keys = err.split(":", maxsplit=1)[1]
        missing_keys = {part.strip() for part in raw_keys.split(",") if part.strip()}
        return bool(missing_keys) and missing_keys.issubset(_SCHEMA_MISSING_KEYS)

    schema_prefixes = (
        "'schema_version'",
        "'schema_uri'",
        "schema_version ",
        "schema_uri ",
    )
    return err.startswith(schema_prefixes)


def _is_same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def cmd_migrate(args: argparse.Namespace) -> int:
    portfolio_path = Path(args.portfolio)
    try:
        portfolio = load_json(portfolio_path)
    except FileNotFoundError:
        print(f"Portfolio not found: {portfolio_path}", file=sys.stderr)
        return 1

    pre_errors = [
        err
        for err in validate_portfolio(portfolio)
        if not _is_schema_only_precheck_error(err)
    ]
    if pre_errors:
        print("Refusing to migrate an invalid portfolio:", file=sys.stderr)
        for err in pre_errors:
            print(f"- {err}", file=sys.stderr)
        return 1

    raw_version = portfolio.get("schema_version")
    if not isinstance(raw_version, str):
        print("Portfolio missing string 'schema_version'", file=sys.stderr)
        return 1

    try:
        current = parse_version(raw_version)
    except ValueError as exc:
        print(f"Invalid schema_version: {exc}", file=sys.stderr)
        return 1

    target_str = args.to or format_version(CURRENT_SCHEMA_VERSION)
    try:
        target = parse_version(target_str)
    except ValueError as exc:
        print(f"Invalid --to: {exc}", file=sys.stderr)
        return 1

    try:
        steps = plan_migrations(current, target)
    except MigrationPlanError as exc:
        print(f"Migration planning failed: {exc}", file=sys.stderr)
        return 1

    if not steps:
        print(
            json.dumps(
                {
                    "from": format_version(current),
                    "to": format_version(target),
                    "status": "noop",
                },
                indent=2,
            )
        )
        return 0

    migrated, applied = apply_migrations(portfolio, steps)

    post_errors = validate_portfolio(migrated)
    if post_errors:
        print("Migration produced an invalid portfolio:", file=sys.stderr)
        for err in post_errors:
            print(f"- {err}", file=sys.stderr)
        return 1

    payload: dict = {
        "from": format_version(current),
        "to": format_version(target),
        "steps": [
            {
                "from": format_version(step.from_version),
                "to": format_version(step.to_version),
                "description": step.description,
                "changes": step.changes,
            }
            for step in applied
        ],
        "dry_run": bool(args.dry_run),
    }

    if args.dry_run:
        payload["status"] = "planned"
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    output_path = Path(args.output) if args.output else portfolio_path
    in_place = _is_same_path(output_path, portfolio_path)
    backup_written: str | None = None
    if in_place and not args.no_backup:
        backup = _backup_path(portfolio_path)
        shutil.copy2(portfolio_path, backup)
        backup_written = str(backup)

    save_json(output_path, migrated)

    payload["status"] = "written"
    payload["output"] = str(output_path)
    if backup_written:
        payload["backup"] = backup_written
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_compact(args: argparse.Namespace) -> int:
    policy = CompactionPolicy(
        daily_days=args.daily_days,
        weekly_days=args.weekly_days,
    )
    journal_path = Path(args.snapshots)
    verify = verify_journal(journal_path)
    payload: dict = {
        "path": str(journal_path),
        "verify": {
            "ok_rows": verify.ok_rows,
            "torn_tail_bytes": verify.torn_tail_bytes,
            "total_bytes": verify.total_bytes,
        },
    }

    rotate_bytes = args.rotate_bytes if args.rotate_bytes is not None else 0

    if args.dry_run:
        from .storage import load_jsonl as _load_jsonl
        from .journal import select_compacted

        rows = _load_jsonl(journal_path)
        kept = select_compacted(rows, policy=policy)
        payload["status"] = "planned"
        payload["policy"] = {
            "daily_days": policy.daily_days,
            "weekly_days": policy.weekly_days,
        }
        if args.rotate:
            current_bytes = journal_path.stat().st_size if journal_path.exists() else 0
            payload["rotation"] = {
                "requested": True,
                "threshold_bytes": rotate_bytes,
                "current_bytes": current_bytes,
                "would_rotate": bool(
                    journal_path.exists() and current_bytes >= rotate_bytes
                ),
            }
        payload["rows_before"] = len(rows)
        payload["rows_after"] = len(kept)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    archived: Path | None = None
    if args.rotate:
        archived = rotate_journal(journal_path, max_bytes=rotate_bytes)
        if archived is not None:
            payload["rotated_to"] = str(archived)

    before, after = compact_snapshots(
        journal_path,
        policy=policy,
        keep_backup=not args.no_backup,
    )
    payload["status"] = "written"
    payload["rows_before"] = before
    payload["rows_after"] = after
    if not args.no_backup:
        payload["backup"] = str(journal_path.with_name(journal_path.name + ".bak"))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _add_workspace_options(
    parser: argparse.ArgumentParser,
    *,
    with_out_root: bool = False,
    with_portfolio_name: bool = False,
    with_registry: bool = False,
) -> None:
    parser.add_argument(
        "--data-dir",
        default=None,
        help=f"Workspace data root (default: {DEFAULT_DATA_DIR})",
    )
    if with_out_root:
        parser.add_argument(
            "--out-root",
            default=None,
            help=f"Workspace output root (default: {DEFAULT_OUT_ROOT})",
        )
    if with_registry:
        parser.add_argument(
            "--registry",
            default=None,
            help=f"Portfolio registry path (default: <data-dir>/{Path(DEFAULT_REGISTRY_PATH).name})",
        )
    if with_portfolio_name:
        parser.add_argument(
            "--portfolio-name",
            default=None,
            help="Use paths from registry entry for this portfolio name",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rikdom")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate portfolio structure")
    p_validate.add_argument("--portfolio", default=None)
    _add_workspace_options(
        p_validate, with_out_root=True, with_portfolio_name=True, with_registry=True
    )
    p_validate.set_defaults(func=cmd_validate)

    p_aggregate = sub.add_parser("aggregate", help="Aggregate holdings by asset class")
    p_aggregate.add_argument("--portfolio", default=None)
    p_aggregate.add_argument("--fx-history", default=None)
    p_aggregate.add_argument(
        "--strict-quality",
        action="store_true",
        help="Treat missing FX conversion warnings as hard errors",
    )
    _add_workspace_options(
        p_aggregate, with_out_root=True, with_portfolio_name=True, with_registry=True
    )
    p_aggregate.set_defaults(func=cmd_aggregate)

    p_snapshot = sub.add_parser(
        "snapshot", help="Append one snapshot into JSONL history"
    )
    p_snapshot.add_argument("--portfolio", default=None)
    p_snapshot.add_argument("--snapshots", default=None)
    p_snapshot.add_argument("--fx-history", default=None)
    p_snapshot.add_argument("--timestamp")
    p_snapshot.add_argument(
        "--no-fx-auto-ingest",
        action="store_true",
        help="Disable automatic fetch of missing FX rates during snapshot",
    )
    p_snapshot.add_argument(
        "--strict-quality",
        action="store_true",
        help="Treat missing FX conversion warnings as hard errors",
    )
    p_snapshot.add_argument(
        "--rotate-bytes",
        type=int,
        default=0,
        help="Rotate --snapshots before appending if it exceeds this size (0 disables)",
    )
    _add_workspace_options(
        p_snapshot, with_out_root=True, with_portfolio_name=True, with_registry=True
    )
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_compact = sub.add_parser(
        "compact", help="Compact and/or rotate a snapshots journal"
    )
    p_compact.add_argument("--snapshots", default=None)
    p_compact.add_argument("--daily-days", type=int, default=DEFAULT_POLICY.daily_days)
    p_compact.add_argument(
        "--weekly-days", type=int, default=DEFAULT_POLICY.weekly_days
    )
    p_compact.add_argument("--dry-run", action="store_true")
    p_compact.add_argument("--no-backup", action="store_true")
    p_compact.add_argument(
        "--rotate",
        action="store_true",
        help="Rotate the journal aside before compacting",
    )
    p_compact.add_argument(
        "--rotate-bytes",
        type=int,
        default=None,
        help=f"Rotate only if above this size (default: always with --rotate; {DEFAULT_ROTATE_BYTES} threshold when set)",
    )
    _add_workspace_options(p_compact)
    p_compact.set_defaults(func=cmd_compact)

    p_viz = sub.add_parser(
        "viz",
        help="Generate plugin-driven quickview + deep-dive HTML reports",
    )
    p_viz.add_argument("--portfolio", default=None)
    p_viz.add_argument("--snapshots", default=None)
    p_viz.add_argument("--fx-history", default=None)
    p_viz.add_argument("--out", default=None)
    p_viz.add_argument("--include-current", action="store_true")
    _add_workspace_options(
        p_viz, with_out_root=True, with_portfolio_name=True, with_registry=True
    )
    p_viz.set_defaults(func=cmd_viz)

    p_import = sub.add_parser(
        "import-statement", help="Import holdings using a community plugin"
    )
    p_import.add_argument("--portfolio", default=None)
    p_import.add_argument("--plugin", required=True)
    p_import.add_argument("--input", required=True)
    p_import.add_argument("--plugins-dir", default="plugins")
    p_import.add_argument("--write", action="store_true")
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Run preflight + merge diff without writing portfolio/import log",
    )
    p_import.add_argument("--import-log", default=None)
    p_import.add_argument(
        "--import-run-id",
        default=None,
        help="Override generated run id (mainly for tests).",
    )
    p_import.add_argument(
        "--ingested-at", default=None, help="Override ingested_at timestamp (ISO-8601)."
    )
    _add_workspace_options(
        p_import, with_out_root=True, with_portfolio_name=True, with_registry=True
    )
    p_import.set_defaults(func=cmd_import_statement)

    p_imports = sub.add_parser("imports", help="Inspect import run history")
    _add_workspace_options(p_imports)
    p_imports_sub = p_imports.add_subparsers(dest="imports_command", required=True)
    p_imports_list = p_imports_sub.add_parser(
        "list", help="List import run log entries"
    )
    p_imports_list.add_argument("--import-log", default=None)
    p_imports_list.add_argument("--source-system", default=None)
    p_imports_list.add_argument("--import-run-id", default=None)
    p_imports_list.add_argument("--limit", type=int, default=0)
    _add_workspace_options(p_imports_list, with_portfolio_name=True, with_registry=True)
    p_imports_list.set_defaults(func=cmd_imports_list)

    p_plugins = sub.add_parser("plugins", help="Inspect plugins")
    p_plugins_sub = p_plugins.add_subparsers(dest="plugins_command", required=True)
    p_plugins_list = p_plugins_sub.add_parser("list", help="List plugin manifests")
    p_plugins_list.add_argument("--plugins-dir", default="plugins")
    p_plugins_list.set_defaults(func=cmd_plugins_list)

    p_plugin = sub.add_parser("plugin", help="Author plugins (scaffold new ones)")
    p_plugin_sub = p_plugin.add_subparsers(dest="plugin_command", required=True)
    p_plugin_init = p_plugin_sub.add_parser(
        "init", help="Scaffold a new plugin from the SDK template"
    )
    p_plugin_init.add_argument(
        "name",
        help="Plugin slug (must match ^[a-z][a-z0-9-]{1,63}$)",
    )
    p_plugin_init.add_argument(
        "--dest",
        default="plugins",
        help="Directory to create the plugin under (default: plugins)",
    )
    p_plugin_init.add_argument(
        "--description",
        default=None,
        help="Human-readable plugin description",
    )
    p_plugin_init.set_defaults(func=cmd_plugin_init)

    p_storage = sub.add_parser(
        "storage-sync", help="Sync canonical JSON into storage plugin"
    )
    p_storage.add_argument("--plugin", default="duckdb-storage")
    p_storage.add_argument("--plugins-dir", default="plugins")
    p_storage.add_argument("--portfolio", default=None)
    p_storage.add_argument("--snapshots", default=None)
    p_storage.add_argument("--db-path", default=None)
    _add_workspace_options(
        p_storage, with_out_root=True, with_portfolio_name=True, with_registry=True
    )
    p_storage.set_defaults(func=cmd_storage_sync)

    p_migrate = sub.add_parser(
        "migrate", help="Upgrade portfolio schema to a newer version"
    )
    p_migrate.add_argument("--portfolio", default=None)
    p_migrate.add_argument(
        "--to",
        default=None,
        help="Target semver (default: current reader CURRENT_SCHEMA_VERSION)",
    )
    p_migrate.add_argument("--dry-run", action="store_true")
    p_migrate.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip writing a .bak-<timestamp> sibling before overwriting",
    )
    p_migrate.add_argument(
        "--output",
        default=None,
        help="Write migrated file here instead of overwriting --portfolio",
    )
    _add_workspace_options(p_migrate, with_portfolio_name=True, with_registry=True)
    p_migrate.set_defaults(func=cmd_migrate)

    p_workspace = sub.add_parser(
        "workspace", help="Manage multi-portfolio workspace registry"
    )
    _add_workspace_options(p_workspace, with_out_root=True, with_registry=True)
    p_workspace_sub = p_workspace.add_subparsers(
        dest="workspace_command", required=True
    )

    p_workspace_init = p_workspace_sub.add_parser(
        "init", help="Initialize portfolio registry"
    )
    _add_workspace_options(p_workspace_init, with_out_root=True, with_registry=True)
    p_workspace_init.add_argument(
        "--portfolios",
        default=",".join(DEFAULT_WORKSPACE_PORTFOLIOS),
        help="Comma-separated portfolio names (default: main,paper,retirement)",
    )
    p_workspace_init.add_argument(
        "--default-portfolio",
        default="main",
        help="Default portfolio name in registry",
    )
    p_workspace_init.add_argument(
        "--force", action="store_true", help="Overwrite existing registry"
    )
    p_workspace_init.add_argument(
        "--seed-sample",
        dest="seed_sample",
        action="store_true",
        help="Seed missing per-portfolio portfolio/snapshots files from data-sample",
    )
    p_workspace_init.add_argument(
        "--no-seed-sample",
        dest="seed_sample",
        action="store_false",
        help="Do not seed portfolio/snapshots sample files",
    )
    p_workspace_init.set_defaults(func=cmd_workspace_init, seed_sample=True)

    p_workspace_list = p_workspace_sub.add_parser(
        "list", help="List registered portfolios"
    )
    _add_workspace_options(p_workspace_list, with_out_root=True, with_registry=True)
    p_workspace_list.set_defaults(func=cmd_workspace_list)

    p_workspace_rollup = p_workspace_sub.add_parser(
        "rollup", help="Aggregate totals across portfolios in the registry"
    )
    _add_workspace_options(p_workspace_rollup, with_out_root=True, with_registry=True)
    p_workspace_rollup.add_argument(
        "--portfolios",
        default=None,
        help="Optional comma-separated portfolio names to include (default: all)",
    )
    p_workspace_rollup.set_defaults(func=cmd_workspace_rollup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _resolve_workspace_args(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _bootstrap_default_workspace(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
