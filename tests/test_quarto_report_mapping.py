from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rikdom.plugin_engine.pipeline import run_output_pipeline


class QuartoPluginTests(unittest.TestCase):
    def test_quarto_plugin_returns_expected_artifact_metadata(self) -> None:
        result = run_output_pipeline(
            plugin_name="quarto-portfolio-report",
            plugins_dir="plugins",
            portfolio_path="tests/fixtures/portfolio.json",
            snapshots_path="tests/fixtures/snapshots.jsonl",
            output_dir="out/reports",
        )
        self.assertEqual(result["plugin"], "quarto-portfolio-report")
        self.assertTrue(any(a["type"] == "html" for a in result["artifacts"]))
        json_artifact = next(a for a in result["artifacts"] if a["type"] == "json")
        payload = json.loads(Path(json_artifact["path"]).read_text(encoding="utf-8"))
        self.assertIn("sections", payload)
        self.assertIn("timeline", payload["sections"])
        self.assertIn("currency_split", payload["sections"])
        self.assertIn("asset_type_breakdown", payload["sections"])

    def test_quarto_plugin_executes_quarto_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            def _fake_quarto_run(cmd, **kwargs):
                output_name = cmd[cmd.index("--output") + 1]
                output_root = Path(cmd[cmd.index("--output-dir") + 1])
                output_root.mkdir(parents=True, exist_ok=True)
                (output_root / output_name).write_text(
                    "<html><body>Rendered by Quarto</body></html>",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with (
                patch("shutil.which", return_value="/usr/local/bin/quarto"),
                patch("subprocess.run", side_effect=_fake_quarto_run) as mock_run,
            ):
                result = run_output_pipeline(
                    plugin_name="quarto-portfolio-report",
                    plugins_dir="plugins",
                    portfolio_path="tests/fixtures/portfolio.json",
                    snapshots_path="tests/fixtures/snapshots.jsonl",
                    output_dir=str(output_dir),
                )

            self.assertEqual(result["warnings"], [])
            html_artifact = next(a for a in result["artifacts"] if a["type"] == "html")
            html_path = Path(html_artifact["path"])
            self.assertTrue(html_path.exists())
            self.assertIn("Rendered by Quarto", html_path.read_text(encoding="utf-8"))
            self.assertEqual(mock_run.call_count, 2)
            first_args, first_kwargs = mock_run.call_args_list[0]
            second_args, second_kwargs = mock_run.call_args_list[1]
            self.assertIn("render", first_args[0])
            self.assertIn("--output-dir", first_args[0])
            self.assertIn("render", second_args[0])
            self.assertIn("--output-dir", second_args[0])
            self.assertEqual(first_kwargs["timeout"], 120)
            self.assertEqual(second_kwargs["timeout"], 120)
            rendered_templates = {
                Path(arg).name
                for call_args, _ in mock_run.call_args_list
                for arg in call_args[0]
                if isinstance(arg, str) and arg.endswith(".qmd")
            }
            self.assertIn("report.qmd", rendered_templates)
            self.assertIn("dashboard.qmd", rendered_templates)

    def test_quarto_plugin_falls_back_when_quarto_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict("os.environ", {"RIKDOM_DISABLE_QUARTO": "1"}):
                result = run_output_pipeline(
                    plugin_name="quarto-portfolio-report",
                    plugins_dir="plugins",
                    portfolio_path="tests/fixtures/portfolio.json",
                    snapshots_path="tests/fixtures/snapshots.jsonl",
                    output_dir=tmp_dir,
                )

            self.assertTrue(result["warnings"])
            self.assertIn("not found", result["warnings"][0].lower())
            html_artifact = next(a for a in result["artifacts"] if a["type"] == "html")
            html_text = Path(html_artifact["path"]).read_text(encoding="utf-8")
            self.assertIn("Fallback", html_text)

    def test_quarto_plugin_falls_back_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch("shutil.which", return_value="/usr/local/bin/quarto"),
                patch(
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired(
                        cmd=["quarto", "render"],
                        timeout=120,
                    ),
                ),
            ):
                result = run_output_pipeline(
                    plugin_name="quarto-portfolio-report",
                    plugins_dir="plugins",
                    portfolio_path="tests/fixtures/portfolio.json",
                    snapshots_path="tests/fixtures/snapshots.jsonl",
                    output_dir=tmp_dir,
                )

            self.assertTrue(result["warnings"])
            self.assertIn("timed out", result["warnings"][0].lower())
            html_artifact = next(a for a in result["artifacts"] if a["type"] == "html")
            self.assertTrue(Path(html_artifact["path"]).exists())

    def test_quarto_plugin_falls_back_on_non_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch("shutil.which", return_value="/usr/local/bin/quarto"),
                patch(
                    "subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["quarto", "render"],
                        returncode=1,
                        stdout="",
                        stderr="render failed",
                    ),
                ),
            ):
                result = run_output_pipeline(
                    plugin_name="quarto-portfolio-report",
                    plugins_dir="plugins",
                    portfolio_path="tests/fixtures/portfolio.json",
                    snapshots_path="tests/fixtures/snapshots.jsonl",
                    output_dir=tmp_dir,
                )

            self.assertTrue(result["warnings"])
            self.assertIn("render failed", result["warnings"][0].lower())
            html_artifact = next(a for a in result["artifacts"] if a["type"] == "html")
            html_text = Path(html_artifact["path"]).read_text(encoding="utf-8")
            self.assertIn("Fallback", html_text)

    def test_quarto_asset_type_breakdown_rolls_debt_class_into_debt_instrument(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            portfolio_path = tmp / "portfolio.json"
            snapshots_path = tmp / "snapshots.jsonl"
            out_dir = tmp / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            portfolio_path.write_text(
                json.dumps(
                    {
                        "profile": {"display_name": "Debt Rollup"},
                        "settings": {"base_currency": "BRL"},
                        "asset_type_catalog": [
                            {"id": "stock", "asset_class": "stocks"},
                            {"id": "tesouro_direto_ipca", "asset_class": "debt"},
                        ],
                        "holdings": [
                            {
                                "id": "h-td",
                                "asset_type_id": "tesouro_direto_ipca",
                                "label": "Tesouro IPCA+",
                                "market_value": {"amount": 28000, "currency": "BRL"},
                            },
                            {
                                "id": "h-cdb",
                                "asset_type_id": "debt_instrument",
                                "label": "CDB",
                                "market_value": {"amount": 1200, "currency": "BRL"},
                            },
                            {
                                "id": "h-stock",
                                "asset_type_id": "stock",
                                "label": "Stock",
                                "market_value": {"amount": 500, "currency": "BRL"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshots_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-21T00:00:00Z",
                        "totals": {"portfolio_value_base": 29700},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_output_pipeline(
                plugin_name="quarto-portfolio-report",
                plugins_dir="plugins",
                portfolio_path=str(portfolio_path),
                snapshots_path=str(snapshots_path),
                output_dir=str(out_dir),
            )

            json_artifact = next(a for a in result["artifacts"] if a["type"] == "json")
            payload = json.loads(
                Path(json_artifact["path"]).read_text(encoding="utf-8")
            )
            breakdown = payload["sections"]["asset_type_breakdown"]

            self.assertEqual(breakdown.get("debt_instrument"), 29200.0)
            self.assertEqual(breakdown.get("stock"), 500.0)
            self.assertNotIn("tesouro_direto_ipca", breakdown)

    def test_quarto_breakdowns_only_aggregate_base_converted_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            portfolio_path = tmp / "portfolio.json"
            snapshots_path = tmp / "snapshots.jsonl"
            out_dir = tmp / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            portfolio_path.write_text(
                json.dumps(
                    {
                        "profile": {"display_name": "FX Portfolio", "country": "BR"},
                        "settings": {"base_currency": "BRL"},
                        "asset_type_catalog": [
                            {"id": "stock", "asset_class": "stocks"},
                            {"id": "fund", "asset_class": "funds"},
                        ],
                        "holdings": [
                            {
                                "id": "h-us-converted",
                                "asset_type_id": "stock",
                                "label": "US Converted",
                                "jurisdiction": {"country": "US"},
                                "market_value": {"amount": 100, "currency": "USD"},
                                "metadata": {"fx_rate_to_base": 5.0},
                            },
                            {
                                "id": "h-us-missing-fx",
                                "asset_type_id": "stock",
                                "label": "US Missing FX",
                                "jurisdiction": {"country": "US"},
                                "market_value": {"amount": 200, "currency": "USD"},
                            },
                            {
                                "id": "h-brl",
                                "asset_type_id": "fund",
                                "label": "Local Fund",
                                "jurisdiction": {"country": "BR"},
                                "market_value": {"amount": 300, "currency": "BRL"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshots_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-21T00:00:00Z",
                        "totals": {"portfolio_value_base": 800},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_output_pipeline(
                plugin_name="quarto-portfolio-report",
                plugins_dir="plugins",
                portfolio_path=str(portfolio_path),
                snapshots_path=str(snapshots_path),
                output_dir=str(out_dir),
            )

            json_artifact = next(a for a in result["artifacts"] if a["type"] == "json")
            payload = json.loads(
                Path(json_artifact["path"]).read_text(encoding="utf-8")
            )
            sections = payload["sections"]

            self.assertEqual(sections["currency_split"].get("USD"), 300.0)
            self.assertEqual(sections["currency_split"].get("BRL"), 300.0)
            self.assertEqual(sections["asset_type_breakdown"].get("stock"), 500.0)
            self.assertEqual(sections["asset_type_breakdown"].get("fund"), 300.0)
            self.assertEqual(sections["geography"].get("US"), 500.0)
            self.assertEqual(sections["geography"].get("BR"), 300.0)

    def test_quarto_top_holdings_handles_malformed_market_value_amount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            portfolio_path = tmp / "portfolio.json"
            snapshots_path = tmp / "snapshots.jsonl"
            out_dir = tmp / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            portfolio_path.write_text(
                json.dumps(
                    {
                        "profile": {"display_name": "Malformed Amounts"},
                        "settings": {"base_currency": "USD"},
                        "asset_type_catalog": [
                            {"id": "stock", "asset_class": "stocks"}
                        ],
                        "holdings": [
                            {
                                "id": "h-good",
                                "asset_type_id": "stock",
                                "label": "Good",
                                "market_value": {"amount": "12.5", "currency": "USD"},
                            },
                            {
                                "id": "h-bad",
                                "asset_type_id": "stock",
                                "label": "Bad",
                                "market_value": {"amount": "", "currency": "USD"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshots_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-21T00:00:00Z",
                        "totals": {"portfolio_value_base": 12.5},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_output_pipeline(
                plugin_name="quarto-portfolio-report",
                plugins_dir="plugins",
                portfolio_path=str(portfolio_path),
                snapshots_path=str(snapshots_path),
                output_dir=str(out_dir),
            )

            json_artifact = next(a for a in result["artifacts"] if a["type"] == "json")
            payload = json.loads(
                Path(json_artifact["path"]).read_text(encoding="utf-8")
            )
            top_holdings = payload["sections"]["risk"]["top_holdings"]

            self.assertEqual(top_holdings[0]["id"], "h-good")
            self.assertEqual(top_holdings[0]["amount"], 12.5)
            self.assertEqual(top_holdings[1]["id"], "h-bad")
            self.assertEqual(top_holdings[1]["amount"], 0.0)

    def test_quarto_currency_split_buckets_malformed_currencies_as_unknown(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            portfolio_path = tmp / "portfolio.json"
            snapshots_path = tmp / "snapshots.jsonl"
            out_dir = tmp / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            portfolio_path.write_text(
                json.dumps(
                    {
                        "profile": {"display_name": "Malformed Currency"},
                        "settings": {"base_currency": "USD"},
                        "asset_type_catalog": [
                            {"id": "stock", "asset_class": "stocks"}
                        ],
                        "holdings": [
                            {
                                "id": "h-usd",
                                "asset_type_id": "stock",
                                "market_value": {"amount": 100, "currency": "USD"},
                            },
                            {
                                "id": "h-bad-length",
                                "asset_type_id": "stock",
                                "market_value": {"amount": 50, "currency": "USDD"},
                            },
                            {
                                "id": "h-bad-digits",
                                "asset_type_id": "stock",
                                "market_value": {"amount": 25, "currency": "US1"},
                            },
                            {
                                "id": "h-empty",
                                "asset_type_id": "stock",
                                "market_value": {"amount": 10, "currency": ""},
                            },
                            {
                                "id": "h-non-ascii",
                                "asset_type_id": "stock",
                                "market_value": {"amount": 7, "currency": "ÅØÆ"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshots_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-21T00:00:00Z",
                        "totals": {"portfolio_value_base": 185},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_output_pipeline(
                plugin_name="quarto-portfolio-report",
                plugins_dir="plugins",
                portfolio_path=str(portfolio_path),
                snapshots_path=str(snapshots_path),
                output_dir=str(out_dir),
            )

            json_artifact = next(a for a in result["artifacts"] if a["type"] == "json")
            payload = json.loads(
                Path(json_artifact["path"]).read_text(encoding="utf-8")
            )
            currency_split = payload["sections"]["currency_split"]

            self.assertEqual(currency_split.get("USD"), 100.0)
            self.assertEqual(currency_split.get("UNKNOWN"), 92.0)
            self.assertNotIn("USDD", currency_split)
            self.assertNotIn("US1", currency_split)
            self.assertNotIn("ÅØÆ", currency_split)

            quickview_currency = payload["sections"]["quickview"]["currency"]
            native = quickview_currency["native"]
            converted_base = quickview_currency["converted_base"]
            missing_rates = quickview_currency["missing_rates"]

            self.assertEqual(native.get("USD"), 100.0)
            self.assertEqual(native.get("UNKNOWN"), 92.0)
            self.assertNotIn("USDD", native)
            self.assertNotIn("US1", native)
            self.assertNotIn("", native)
            self.assertNotIn("ÅØÆ", native)
            self.assertEqual(converted_base.get("USD"), 100.0)
            self.assertNotIn("UNKNOWN", converted_base)
            self.assertIn("UNKNOWN", missing_rates)

    def test_quarto_report_does_not_crash_on_invalid_base_currency(self) -> None:
        """Malformed `settings.base_currency` must not crash rendering.

        The dashboard JS validates currency codes against `^[A-Z]{3}$`
        and falls back to a safe default; the Python side should also
        produce a JSON payload without raising.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            portfolio_path = tmp / "portfolio.json"
            snapshots_path = tmp / "snapshots.jsonl"
            out_dir = tmp / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            portfolio_path.write_text(
                json.dumps(
                    {
                        "profile": {"display_name": "Bad Currency"},
                        "settings": {"base_currency": "not-a-code"},
                        "asset_type_catalog": [
                            {"id": "stock", "asset_class": "stocks"}
                        ],
                        "holdings": [
                            {
                                "id": "h1",
                                "asset_type_id": "stock",
                                "market_value": {"amount": 100, "currency": "USD"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshots_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-21T00:00:00Z",
                        "totals": {"portfolio_value_base": 100},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            # Must not raise.
            result = run_output_pipeline(
                plugin_name="quarto-portfolio-report",
                plugins_dir="plugins",
                portfolio_path=str(portfolio_path),
                snapshots_path=str(snapshots_path),
                output_dir=str(out_dir),
            )

            json_artifact = next(a for a in result["artifacts"] if a["type"] == "json")
            payload = json.loads(
                Path(json_artifact["path"]).read_text(encoding="utf-8")
            )
            self.assertIn("sections", payload)


if __name__ == "__main__":
    unittest.main()
