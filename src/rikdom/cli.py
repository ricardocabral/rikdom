from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .aggregate import aggregate_portfolio
from .plugins import PluginError, merge_holdings, run_import_plugin
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
        imported = run_import_plugin(args.plugin, args.input, args.plugins_dir)
    except PluginError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    merged, inserted, updated = merge_holdings(portfolio, imported)
    if args.write:
        save_json(args.portfolio, merged)

    print(
        json.dumps(
            {
                "plugin": args.plugin,
                "inserted": inserted,
                "updated": updated,
                "write": bool(args.write),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
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
    p_import.add_argument("--plugins-dir", default="plugins/community")
    p_import.add_argument("--write", action="store_true")
    p_import.set_defaults(func=cmd_import_statement)

    return parser



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
