from __future__ import annotations

import io
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from rikdom.cli import cmd_snapshot
from rikdom.storage import load_jsonl


class CliSnapshotFxTests(unittest.TestCase):
    def test_cmd_snapshot_uses_fx_lock_and_persists_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            snapshots_path = tmp / "snapshots.jsonl"
            fx_history_path = tmp / "fx_rates.jsonl"
            args = Namespace(
                portfolio=str(tmp / "portfolio.json"),
                snapshots=str(snapshots_path),
                timestamp="2026-04-21T10:00:00Z",
                rotate_bytes=0,
                fx_history=str(fx_history_path),
                no_fx_auto_ingest=False,
            )
            portfolio = {
                "settings": {"base_currency": "BRL"},
                "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
                "holdings": [
                    {
                        "id": "h-us",
                        "asset_type_id": "stock",
                        "label": "US Asset",
                        "market_value": {"amount": 100, "currency": "USD"},
                    }
                ],
            }
            lock = {
                "base_currency": "BRL",
                "snapshot_timestamp": "2026-04-21T10:00:00Z",
                "rates_to_base": {"USD": 5.0},
                "rate_dates": {"USD": "2026-04-21"},
                "sources": {"USD": "auto_ingest"},
            }

            with (
                mock.patch("rikdom.cli.load_json", return_value=portfolio),
                mock.patch("rikdom.cli.ensure_snapshot_fx_lock", return_value=(lock, [])) as mock_fx,
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = cmd_snapshot(args)

            self.assertEqual(code, 0)
            mock_fx.assert_called_once_with(
                portfolio,
                fx_history_path=str(fx_history_path),
                snapshot_timestamp="2026-04-21T10:00:00Z",
                auto_ingest=True,
            )

            rows = load_jsonl(snapshots_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["metadata"]["fx_lock"]["rates_to_base"]["USD"], 5.0)


if __name__ == "__main__":
    unittest.main()
