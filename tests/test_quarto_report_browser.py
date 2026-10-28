"""Opt-in real-browser regression checks without a runtime browser dependency."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rikdom.plugin_engine.pipeline import run_output_pipeline


@unittest.skipUnless(
    os.environ.get("RIKDOM_PLAYWRIGHT_MODULE") and shutil.which("node"),
    "Set RIKDOM_PLAYWRIGHT_MODULE to an installed Playwright module for browser QA",
)
class OfflineReportBrowserTests(unittest.TestCase):
    def test_generated_reports_work_after_relocation_without_remote_network(self):
        for fallback in (True, False):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                generated = root / "generated"
                environment = dict(os.environ)
                environment.pop("RIKDOM_DISABLE_QUARTO", None)
                if fallback:
                    environment["RIKDOM_DISABLE_QUARTO"] = "1"
                with patch.dict(os.environ, environment, clear=True):
                    result = run_output_pipeline(
                        plugin_name="quarto-portfolio-report", plugins_dir="plugins",
                        portfolio_path="tests/fixtures/portfolio.json",
                        snapshots_path="tests/fixtures/snapshots.jsonl",
                        output_dir=str(generated),
                    )
                if not fallback and result["warnings"]:
                    self.fail("Full Quarto rendering required for this opt-in check: " + str(result["warnings"]))
                # The temporary render workspace has already been deleted. Moving the
                # bundle also catches hidden absolute references to the output path.
                relocated = root / "relocated"
                generated.rename(relocated)
                checked = subprocess.run(
                    [shutil.which("node"), "tests/browser/report_offline.cjs", str(relocated),
                     "fallback" if fallback else "quarto"],
                    text=True, capture_output=True, timeout=120,
                )
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
