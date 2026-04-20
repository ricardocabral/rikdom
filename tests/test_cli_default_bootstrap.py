from __future__ import annotations

import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from rikdom.cli import (
    DEFAULT_PORTFOLIO_PATH,
    DEFAULT_SNAPSHOTS_PATH,
    SAMPLE_PORTFOLIO_PATH,
    SAMPLE_SNAPSHOTS_PATH,
    _bootstrap_default_workspace,
)


class CliDefaultBootstrapTests(unittest.TestCase):
    def test_bootstraps_missing_default_files_from_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path(SAMPLE_PORTFOLIO_PATH).parent.mkdir(parents=True, exist_ok=True)
                Path(SAMPLE_PORTFOLIO_PATH).write_text('{"profile": {"display_name": "Sample"}}\n', encoding="utf-8")
                Path(SAMPLE_SNAPSHOTS_PATH).write_text('{"timestamp":"2026-01-01T00:00:00Z"}\n', encoding="utf-8")

                args = Namespace(
                    portfolio=DEFAULT_PORTFOLIO_PATH,
                    snapshots=DEFAULT_SNAPSHOTS_PATH,
                )
                _bootstrap_default_workspace(args)

                self.assertTrue(Path(DEFAULT_PORTFOLIO_PATH).exists())
                self.assertTrue(Path(DEFAULT_SNAPSHOTS_PATH).exists())
                self.assertEqual(
                    Path(DEFAULT_PORTFOLIO_PATH).read_text(encoding="utf-8"),
                    Path(SAMPLE_PORTFOLIO_PATH).read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    Path(DEFAULT_SNAPSHOTS_PATH).read_text(encoding="utf-8"),
                    Path(SAMPLE_SNAPSHOTS_PATH).read_text(encoding="utf-8"),
                )
            finally:
                os.chdir(cwd)

    def test_does_not_bootstrap_custom_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path(SAMPLE_PORTFOLIO_PATH).parent.mkdir(parents=True, exist_ok=True)
                Path(SAMPLE_PORTFOLIO_PATH).write_text('{"profile": {"display_name": "Sample"}}\n', encoding="utf-8")
                Path(SAMPLE_SNAPSHOTS_PATH).write_text('{"timestamp":"2026-01-01T00:00:00Z"}\n', encoding="utf-8")

                args = Namespace(
                    portfolio="custom/portfolio.json",
                    snapshots="custom/snapshots.jsonl",
                )
                _bootstrap_default_workspace(args)

                self.assertFalse(Path("custom/portfolio.json").exists())
                self.assertFalse(Path("custom/snapshots.jsonl").exists())
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
