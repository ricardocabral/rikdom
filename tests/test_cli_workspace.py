from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rikdom.cli import (
    _validate_portfolio_name,
    _resolve_workspace_args,
    build_parser,
    main,
)
from rikdom.storage import save_json


def _sample_portfolio(*, base_currency: str, amount: float, asset_class: str = "stocks") -> dict:
    return {
        "schema_version": "1.2.0",
        "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
        "profile": {
            "portfolio_id": f"demo-{base_currency.lower()}",
            "owner_kind": "individual",
            "display_name": f"Demo {base_currency}",
        },
        "settings": {"base_currency": base_currency},
        "asset_type_catalog": [{"id": "stock", "asset_class": asset_class}],
        "holdings": [
            {
                "id": "h1",
                "asset_type_id": "stock",
                "market_value": {"amount": amount, "currency": base_currency},
            }
        ],
    }


def _run(args: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class CliWorkspaceTests(unittest.TestCase):
    def test_resolve_workspace_defaults_from_data_dir(self) -> None:
        args = Namespace(
            data_dir="workspace-data",
            out_root="workspace-out",
            registry=None,
            portfolio_name=None,
            portfolio=None,
            snapshots=None,
            import_log=None,
            out=None,
            out_dir=None,
            db_path=None,
        )

        _resolve_workspace_args(args)

        self.assertEqual(args.portfolio, "workspace-data/portfolio.json")
        self.assertEqual(args.snapshots, "workspace-data/snapshots.jsonl")
        self.assertEqual(args.import_log, "workspace-data/import_log.jsonl")
        self.assertEqual(args.registry, "workspace-data/portfolio_registry.json")
        self.assertEqual(args.out, "workspace-out/dashboard.html")
        self.assertEqual(args.out_dir, "workspace-out/reports")
        self.assertEqual(args.db_path, "workspace-out/rikdom.duckdb")

    def test_resolve_workspace_portfolio_name_uses_registry_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                save_json(
                    "workspace-data/portfolio_registry.json",
                    {
                        "schema_version": "1.0",
                        "default_portfolio": "main",
                        "portfolios": [
                            {
                                "name": "paper",
                                "portfolio": "custom/paper-portfolio.json",
                                "snapshots": "custom/paper-snapshots.jsonl",
                                "import_log": "custom/paper-import-log.jsonl",
                            }
                        ],
                    },
                )
                args = Namespace(
                    data_dir="workspace-data",
                    out_root="workspace-out",
                    registry=None,
                    portfolio_name="paper",
                    portfolio=None,
                    snapshots=None,
                    import_log=None,
                    out=None,
                    out_dir=None,
                    db_path=None,
                )
                _resolve_workspace_args(args)

                self.assertEqual(args.portfolio, "custom/paper-portfolio.json")
                self.assertEqual(args.snapshots, "custom/paper-snapshots.jsonl")
                self.assertEqual(args.import_log, "custom/paper-import-log.jsonl")
                self.assertEqual(args.out, "workspace-out/paper/dashboard.html")
                self.assertEqual(args.out_dir, "workspace-out/reports/paper")
                self.assertEqual(args.db_path, "workspace-out/paper/rikdom.duckdb")
            finally:
                os.chdir(cwd)

    def test_workspace_rollup_single_currency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                code, _, stderr = _run(
                    [
                        "workspace",
                        "init",
                        "--data-dir",
                        "workspace-data",
                        "--out-root",
                        "workspace-out",
                        "--portfolios",
                        "main,paper",
                        "--force",
                        "--no-seed-sample",
                    ]
                )
                self.assertEqual(code, 0, stderr)

                save_json(
                    "workspace-data/portfolios/main/portfolio.json",
                    _sample_portfolio(base_currency="BRL", amount=100.0, asset_class="stocks"),
                )
                save_json(
                    "workspace-data/portfolios/paper/portfolio.json",
                    _sample_portfolio(base_currency="BRL", amount=50.0, asset_class="funds"),
                )

                code, stdout, stderr = _run(
                    ["workspace", "rollup", "--data-dir", "workspace-data"]
                )
                self.assertEqual(code, 0, stderr)
                payload = json.loads(stdout)
                self.assertEqual(payload["base_currency"], "BRL")
                self.assertEqual(payload["totals"]["portfolio_value_base"], 150.0)
                self.assertEqual(payload["totals"]["by_asset_class"]["stocks"], 100.0)
                self.assertEqual(payload["totals"]["by_asset_class"]["funds"], 50.0)
            finally:
                os.chdir(cwd)

    def test_workspace_rollup_multi_currency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                code, _, stderr = _run(
                    [
                        "workspace",
                        "init",
                        "--data-dir",
                        "workspace-data",
                        "--portfolios",
                        "main,retirement",
                        "--force",
                        "--no-seed-sample",
                    ]
                )
                self.assertEqual(code, 0, stderr)

                save_json(
                    "workspace-data/portfolios/main/portfolio.json",
                    _sample_portfolio(base_currency="BRL", amount=100.0),
                )
                save_json(
                    "workspace-data/portfolios/retirement/portfolio.json",
                    _sample_portfolio(base_currency="USD", amount=80.0),
                )

                code, stdout, stderr = _run(
                    ["workspace", "rollup", "--data-dir", "workspace-data"]
                )
                self.assertEqual(code, 0, stderr)
                payload = json.loads(stdout)
                self.assertIn("totals_by_currency", payload)
                self.assertEqual(payload["totals_by_currency"]["BRL"]["portfolio_value_base"], 100.0)
                self.assertEqual(payload["totals_by_currency"]["USD"]["portfolio_value_base"], 80.0)
            finally:
                os.chdir(cwd)


class PortfolioNameValidationTests(unittest.TestCase):
    def test_accepts_standard_names(self) -> None:
        for name in ("main", "paper", "main.v2", "retirement_2025", "a-b_c.d", "_hidden", "A1"):
            with self.subTest(name=name):
                self.assertEqual(_validate_portfolio_name(name), name)

    def test_rejects_traversal_and_separators(self) -> None:
        for name in (
            "",
            ".hidden",
            "-leading",
            "..",
            "../etc",
            "foo/bar",
            "foo\\bar",
            "foo..bar",
            "foo bar",
            "foo:bar",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    _validate_portfolio_name(name)


class CliOutRootParsingTests(unittest.TestCase):
    def test_out_root_accepted_by_workspace_commands(self) -> None:
        parser = build_parser()
        cases = [
            ["validate", "--out-root", "custom-out"],
            ["aggregate", "--out-root", "custom-out"],
            ["snapshot", "--out-root", "custom-out"],
            [
                "import-statement",
                "--plugin",
                "csv-generic",
                "--input",
                "data-sample/sample_statement.csv",
                "--out-root",
                "custom-out",
            ],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                ns = parser.parse_args(argv)
                self.assertEqual(ns.out_root, "custom-out")


if __name__ == "__main__":
    unittest.main()
