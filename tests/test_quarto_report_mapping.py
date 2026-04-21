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
            self.assertEqual(mock_run.call_count, 1)
            args, kwargs = mock_run.call_args
            self.assertIn("render", args[0])
            self.assertIn("--output-dir", args[0])
            self.assertEqual(kwargs["timeout"], 120)

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

    def test_quarto_asset_type_breakdown_rolls_debt_class_into_debt_instrument(self) -> None:
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
            payload = json.loads(Path(json_artifact["path"]).read_text(encoding="utf-8"))
            breakdown = payload["sections"]["asset_type_breakdown"]

            self.assertEqual(breakdown.get("debt_instrument"), 29200.0)
            self.assertEqual(breakdown.get("stock"), 500.0)
            self.assertNotIn("tesouro_direto_ipca", breakdown)


if __name__ == "__main__":
    unittest.main()
