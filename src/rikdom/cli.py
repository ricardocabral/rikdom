from __future__ import annotations

import argparse
import json
import sys

from .aggregate import aggregate_portfolio
from .plugin_engine.errors import PluginEngineError
from .plugin_engine.loader import discover_plugins
from .plugin_engine.pipeline import (
    run_import_pipeline,
    run_output_pipeline,
    run_storage_sync_pipeline,
)
from .plugins import merge_activities, merge_holdings
from .snapshot import snapshot_from_aggregate
from .storage import append_jsonl, load_json, load_jsonl, save_json
from .validate import validate_portfolio
from .visualize import write_dashboard



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



def cmd_import_statement(args: argparse.Namespace) -> int:
    portfolio = load_json(args.portfolio)
    try:
        imported = run_import_pipeline(args.plugin, args.plugins_dir, args.input)
    except PluginEngineError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    merged, h_inserted, h_updated = merge_holdings(portfolio, imported)
    merged, a_inserted, a_updated = merge_activities(merged, imported)
    if args.write:
        save_json(args.portfolio, merged)

    print(
        json.dumps(
            {
                "plugin": args.plugin,
                "holdings": {"inserted": h_inserted, "updated": h_updated},
                "activities": {"inserted": a_inserted, "updated": a_updated},
                "write": bool(args.write),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
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



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rikdom")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate portfolio structure")
    p_validate.add_argument("--portfolio", default="data/portfolio.json")
    p_validate.set_defaults(func=cmd_validate)

    p_aggregate = sub.add_parser("aggregate", help="Aggregate holdings by asset class")
    p_aggregate.add_argument("--portfolio", default="data/portfolio.json")
    p_aggregate.set_defaults(func=cmd_aggregate)

    p_snapshot = sub.add_parser("snapshot", help="Append one snapshot into JSONL history")
    p_snapshot.add_argument("--portfolio", default="data/portfolio.json")
    p_snapshot.add_argument("--snapshots", default="data/snapshots.jsonl")
    p_snapshot.add_argument("--timestamp")
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_visualize = sub.add_parser("visualize", help="Generate static HTML dashboard")
    p_visualize.add_argument("--portfolio", default="data/portfolio.json")
    p_visualize.add_argument("--snapshots", default="data/snapshots.jsonl")
    p_visualize.add_argument("--out", default="out/dashboard.html")
    p_visualize.add_argument("--include-current", action="store_true")
    p_visualize.set_defaults(func=cmd_visualize)

    p_import = sub.add_parser("import-statement", help="Import holdings using a community plugin")
    p_import.add_argument("--portfolio", default="data/portfolio.json")
    p_import.add_argument("--plugin", required=True)
    p_import.add_argument("--input", required=True)
    p_import.add_argument("--plugins-dir", default="plugins")
    p_import.add_argument("--write", action="store_true")
    p_import.set_defaults(func=cmd_import_statement)

    p_plugins = sub.add_parser("plugins", help="Inspect plugins")
    p_plugins_sub = p_plugins.add_subparsers(dest="plugins_command", required=True)
    p_plugins_list = p_plugins_sub.add_parser("list", help="List plugin manifests")
    p_plugins_list.add_argument("--plugins-dir", default="plugins")
    p_plugins_list.set_defaults(func=cmd_plugins_list)

    p_render = sub.add_parser("render-report", help="Render report using output plugin")
    p_render.add_argument("--plugin", default="quarto-portfolio-report")
    p_render.add_argument("--plugins-dir", default="plugins")
    p_render.add_argument("--portfolio", default="data/portfolio.json")
    p_render.add_argument("--snapshots", default="data/snapshots.jsonl")
    p_render.add_argument("--out-dir", default="out/reports")
    p_render.set_defaults(func=cmd_render_report)

    p_storage = sub.add_parser("storage-sync", help="Sync canonical JSON into storage plugin")
    p_storage.add_argument("--plugin", default="duckdb-storage")
    p_storage.add_argument("--plugins-dir", default="plugins")
    p_storage.add_argument("--portfolio", default="data/portfolio.json")
    p_storage.add_argument("--snapshots", default="data/snapshots.jsonl")
    p_storage.add_argument("--db-path", default="out/rikdom.duckdb")
    p_storage.set_defaults(func=cmd_storage_sync)

    return parser



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
