from __future__ import annotations

import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from rikdom.cli import cmd_aggregate, cmd_snapshot


class CliQualityGuardrailsTests(unittest.TestCase):
    def test_cmd_aggregate_strict_quality_returns_error_when_missing_fx(self) -> None:
        args = Namespace(
            portfolio="tests/fixtures/portfolio.json",
            fx_history="tests/fixtures/fx_rates.jsonl",
            strict_quality=True,
        )
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-us",
                    "asset_type_id": "stock",
                    "label": "US Asset",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                }
            ],
        }

        with (
            mock.patch("rikdom.cli.load_json", return_value=portfolio),
            mock.patch(
                "rikdom.cli.ensure_snapshot_fx_lock",
                return_value=({"rates_to_base": {}}, []),
            ),
        ):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cmd_aggregate(args)

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["errors"])
        self.assertIn("strict mode", stderr.getvalue().lower())

    def test_cmd_snapshot_strict_quality_blocks_snapshot_append(self) -> None:
        args = Namespace(
            portfolio="tests/fixtures/portfolio.json",
            snapshots="tests/fixtures/snapshots.jsonl",
            timestamp="2026-04-21T10:00:00Z",
            rotate_bytes=0,
            fx_history="tests/fixtures/fx_rates.jsonl",
            no_fx_auto_ingest=False,
            strict_quality=True,
        )
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
            "holdings": [
                {
                    "id": "h-us",
                    "asset_type_id": "stock",
                    "label": "US Asset",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                }
            ],
        }

        with (
            mock.patch("rikdom.cli.load_json", return_value=portfolio),
            mock.patch(
                "rikdom.cli.ensure_snapshot_fx_lock",
                return_value=({"rates_to_base": {}}, []),
            ),
            mock.patch("rikdom.cli.append_jsonl") as mock_append,
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = cmd_snapshot(args)

        self.assertEqual(code, 1)
        mock_append.assert_not_called()
        self.assertIn("strict mode", stderr.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
