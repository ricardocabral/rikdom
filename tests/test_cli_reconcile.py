from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rikdom.cli import main as cli_main
from rikdom.storage import save_json


def _portfolio() -> dict:
    return {
        "schema_version": "1.0.0",
        "settings": {"base_currency": "USD"},
        "asset_type_catalog": [
            {"id": "stock", "asset_class": "equity"},
        ],
        "holdings": [
            {
                "id": "h-usd",
                "asset_type_id": "stock",
                "quantity": 1,
                "market_value": {"amount": 100.0, "currency": "USD"},
            },
            {
                "id": "h-missing",
                "asset_type_id": "stock",
                "quantity": 1,
                "market_value": {"amount": 50.0, "currency": "EUR"},
            },
        ],
        "activities": [],
    }


class CliReconcileTests(unittest.TestCase):
    def _run(self, *cli_args: str) -> int:
        return cli_main(list(cli_args))

    def test_writes_four_report_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            out_root = Path(tmp) / "out"
            data_dir.mkdir()
            portfolio_path = data_dir / "portfolio.json"
            save_json(str(portfolio_path), _portfolio())

            rc = self._run(
                "reconcile",
                "--data-dir",
                str(data_dir),
                "--out-root",
                str(out_root),
            )
            self.assertEqual(rc, 0)

            reports_dir = out_root / "reports"
            for name in (
                "holding_trust.json",
                "holding_trust.md",
                "reconciliation.json",
                "reconciliation.md",
            ):
                self.assertTrue(
                    (reports_dir / name).exists(), f"missing {name}"
                )

            trust = json.loads((reports_dir / "holding_trust.json").read_text())
            self.assertEqual(trust["base_currency"], "USD")
            self.assertEqual(len(trust["holdings"]), 2)
            self.assertTrue(trust["invariant"]["matches"])
            self.assertIn("h-missing", trust["invariant"]["excluded_holding_ids"])

            recon = json.loads((reports_dir / "reconciliation.json").read_text())
            self.assertGreater(recon["summary"]["total"], 0)
            self.assertIn("RECON_FX_MISSING", recon["summary"]["by_code"])

    def test_strict_mode_returns_nonzero_when_fx_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            out_root = Path(tmp) / "out"
            data_dir.mkdir()
            save_json(str(data_dir / "portfolio.json"), _portfolio())

            rc = self._run(
                "reconcile",
                "--data-dir",
                str(data_dir),
                "--out-root",
                str(out_root),
                "--strict-quality",
            )
            self.assertEqual(rc, 1)
            # files should still be produced for diagnostics
            self.assertTrue(
                (out_root / "reports" / "reconciliation.json").exists()
            )

    def test_format_json_only_skips_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            out_root = Path(tmp) / "out"
            data_dir.mkdir()
            save_json(str(data_dir / "portfolio.json"), _portfolio())

            rc = self._run(
                "reconcile",
                "--data-dir",
                str(data_dir),
                "--out-root",
                str(out_root),
                "--format",
                "json",
            )
            self.assertEqual(rc, 0)
            reports_dir = out_root / "reports"
            self.assertTrue((reports_dir / "holding_trust.json").exists())
            self.assertTrue((reports_dir / "reconciliation.json").exists())
            self.assertFalse((reports_dir / "holding_trust.md").exists())
            self.assertFalse((reports_dir / "reconciliation.md").exists())


    def test_portfolio_name_writes_to_scoped_reports_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            out_root = Path(tmp) / "out"
            scoped_data = data_dir / "portfolios" / "paper"
            scoped_data.mkdir(parents=True)
            save_json(str(scoped_data / "portfolio.json"), _portfolio())
            save_json(
                str(data_dir / "portfolio_registry.json"),
                {
                    "schema_version": "1.0",
                    "default_portfolio": "paper",
                    "portfolios": [{"name": "paper"}],
                },
            )

            rc = self._run(
                "reconcile",
                "--data-dir",
                str(data_dir),
                "--out-root",
                str(out_root),
                "--portfolio-name",
                "paper",
            )
            self.assertEqual(rc, 0)

            scoped_reports = out_root / "reports" / "paper"
            for name in (
                "holding_trust.json",
                "holding_trust.md",
                "reconciliation.json",
                "reconciliation.md",
            ):
                self.assertTrue(
                    (scoped_reports / name).exists(),
                    f"missing {name} in scoped reports dir",
                )
            self.assertFalse((out_root / "reports" / "holding_trust.json").exists())

    def test_explicit_out_dir_overrides_workspace_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            out_root = Path(tmp) / "out"
            custom_dir = Path(tmp) / "custom-reports"
            data_dir.mkdir()
            save_json(str(data_dir / "portfolio.json"), _portfolio())

            rc = self._run(
                "reconcile",
                "--data-dir",
                str(data_dir),
                "--out-root",
                str(out_root),
                "--out-dir",
                str(custom_dir),
            )
            self.assertEqual(rc, 0)
            self.assertTrue((custom_dir / "reconciliation.json").exists())


if __name__ == "__main__":
    unittest.main()
