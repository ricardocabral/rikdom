from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .aggregate import aggregate_portfolio
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
    run_import_pipeline,
    run_output_pipeline,
    run_storage_sync_pipeline,
)
from .plugins import MergeCounts, merge_activities, merge_holdings, stamp_provenance
from .snapshot import snapshot_from_aggregate
from .storage import append_jsonl, load_json, load_jsonl, save_json
from .validate import CURRENT_SCHEMA_VERSION, validate_portfolio
from .visualize import write_dashboard


DEFAULT_PORTFOLIO_PATH = "data/portfolio.json"
DEFAULT_SNAPSHOTS_PATH = "data/snapshots.jsonl"
DEFAULT_IMPORT_LOG = "data/import_log.jsonl"

SAMPLE_PORTFOLIO_PATH = "data-sample/portfolio.json"
SAMPLE_SNAPSHOTS_PATH = "data-sample/snapshots.jsonl"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bootstrap_default_file(path: str, default_path: str, sample_path: str) -> None:
    if path != default_path:
        return

    target = Path(path)
    if target.exists():
        return

    sample = Path(sample_path)
    if not sample.exists():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(sample.read_bytes())


def _bootstrap_default_workspace(args: argparse.Namespace) -> None:
    portfolio_path = getattr(args, "portfolio", None)
    if isinstance(portfolio_path, str):
        _bootstrap_default_file(portfolio_path, DEFAULT_PORTFOLIO_PATH, SAMPLE_PORTFOLIO_PATH)

    snapshots_path = getattr(args, "snapshots", None)
    if isinstance(snapshots_path, str):
        _bootstrap_default_file(snapshots_path, DEFAULT_SNAPSHOTS_PATH, SAMPLE_SNAPSHOTS_PATH)


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
    result = aggregate_portfolio(portfolio)
    output = {
        "base_currency": result.base_currency,
        "portfolio_value_base": result.total_value_base,
        "by_asset_class": result.by_asset_class,
        "warnings": result.warnings,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0



def cmd_snapshot(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    result = aggregate_portfolio(portfolio)
    snap = snapshot_from_aggregate(result, timestamp=args.timestamp)
    append_jsonl(args.snapshots, snap)
    print(f"Snapshot appended to {args.snapshots}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    return 0



def cmd_visualize(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    snapshots = load_jsonl(args.snapshots)

    if args.include_current:
        aggregate = aggregate_portfolio(portfolio)
        snapshots = snapshots + [snapshot_from_aggregate(aggregate)]

    profile = portfolio.get("profile", {}).get("display_name", "Portfolio")
    currency = portfolio.get("settings", {}).get("base_currency", "USD")

    out_file = write_dashboard(profile, currency, snapshots, args.out)
    print(f"Dashboard written to {out_file}")
    return 0



def _counts_dict(counts: MergeCounts) -> dict[str, int]:
    return {"inserted": counts.inserted, "updated": counts.updated, "skipped": counts.skipped}


def cmd_import_statement(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    try:
        imported = run_import_pipeline(args.plugin, args.plugins_dir, args.input)
    except PluginEngineError as exc:
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

    merged, h_counts = merge_holdings(portfolio, imported)
    merged, a_counts = merge_activities(merged, imported)
    if args.write:
        save_json(args.portfolio, merged)

    log_entry = {
        "import_run_id": import_run_id,
        "ingested_at": ingested_at,
        "source_system": source_system,
        "plugin": args.plugin,
        "input": args.input,
        "holdings": _counts_dict(h_counts),
        "activities": _counts_dict(a_counts),
        "write": bool(args.write),
    }

    if args.import_log and args.write:
        append_jsonl(args.import_log, log_entry)

    print(json.dumps(log_entry, indent=2, ensure_ascii=False))
    return 0


def cmd_imports_list(args: argparse.Namespace) -> int:
    entries = load_jsonl(args.import_log)
    if args.source_system:
        entries = [e for e in entries if e.get("source_system") == args.source_system]
    if args.import_run_id:
        entries = [e for e in entries if e.get("import_run_id") == args.import_run_id]
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



def _backup_path(portfolio_path: Path) -> Path:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return portfolio_path.with_name(f"{portfolio_path.name}.bak-{stamp}")


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
        if not err.startswith("schema_version")
        and not err.startswith("schema_uri")
        and not err.startswith("'schema_version'")
        and not err.startswith("'schema_uri'")
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
    backup_written: str | None = None
    if not args.output and not args.no_backup:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rikdom")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate portfolio structure")
    p_validate.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
    p_validate.set_defaults(func=cmd_validate)

    p_aggregate = sub.add_parser("aggregate", help="Aggregate holdings by asset class")
    p_aggregate.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
    p_aggregate.set_defaults(func=cmd_aggregate)

    p_snapshot = sub.add_parser("snapshot", help="Append one snapshot into JSONL history")
    p_snapshot.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
    p_snapshot.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS_PATH)
    p_snapshot.add_argument("--timestamp")
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_visualize = sub.add_parser("visualize", help="Generate static HTML dashboard")
    p_visualize.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
    p_visualize.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS_PATH)
    p_visualize.add_argument("--out", default="out/dashboard.html")
    p_visualize.add_argument("--include-current", action="store_true")
    p_visualize.set_defaults(func=cmd_visualize)

    p_import = sub.add_parser("import-statement", help="Import holdings using a community plugin")
    p_import.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
    p_import.add_argument("--plugin", required=True)
    p_import.add_argument("--input", required=True)
    p_import.add_argument("--plugins-dir", default="plugins")
    p_import.add_argument("--write", action="store_true")
    p_import.add_argument("--import-log", default=DEFAULT_IMPORT_LOG)
    p_import.add_argument("--import-run-id", default=None, help="Override generated run id (mainly for tests).")
    p_import.add_argument("--ingested-at", default=None, help="Override ingested_at timestamp (ISO-8601).")
    p_import.set_defaults(func=cmd_import_statement)

    p_imports = sub.add_parser("imports", help="Inspect import run history")
    p_imports_sub = p_imports.add_subparsers(dest="imports_command", required=True)
    p_imports_list = p_imports_sub.add_parser("list", help="List import run log entries")
    p_imports_list.add_argument("--import-log", default=DEFAULT_IMPORT_LOG)
    p_imports_list.add_argument("--source-system", default=None)
    p_imports_list.add_argument("--import-run-id", default=None)
    p_imports_list.add_argument("--limit", type=int, default=0)
    p_imports_list.set_defaults(func=cmd_imports_list)

    p_plugins = sub.add_parser("plugins", help="Inspect plugins")
    p_plugins_sub = p_plugins.add_subparsers(dest="plugins_command", required=True)
    p_plugins_list = p_plugins_sub.add_parser("list", help="List plugin manifests")
    p_plugins_list.add_argument("--plugins-dir", default="plugins")
    p_plugins_list.set_defaults(func=cmd_plugins_list)

    p_render = sub.add_parser("render-report", help="Render report using output plugin")
    p_render.add_argument("--plugin", default="quarto-portfolio-report")
    p_render.add_argument("--plugins-dir", default="plugins")
    p_render.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
    p_render.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS_PATH)
    p_render.add_argument("--out-dir", default="out/reports")
    p_render.set_defaults(func=cmd_render_report)

    p_storage = sub.add_parser("storage-sync", help="Sync canonical JSON into storage plugin")
    p_storage.add_argument("--plugin", default="duckdb-storage")
    p_storage.add_argument("--plugins-dir", default="plugins")
    p_storage.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
    p_storage.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS_PATH)
    p_storage.add_argument("--db-path", default="out/rikdom.duckdb")
    p_storage.set_defaults(func=cmd_storage_sync)

    p_migrate = sub.add_parser("migrate", help="Upgrade portfolio schema to a newer version")
    p_migrate.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH)
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
    p_migrate.set_defaults(func=cmd_migrate)

    return parser



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _bootstrap_default_workspace(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
