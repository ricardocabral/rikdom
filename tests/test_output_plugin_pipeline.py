from __future__ import annotations

import unittest
from pathlib import Path

from rikdom.plugin_engine.pipeline import run_output_pipeline


class OutputPipelineTests(unittest.TestCase):
    def test_run_output_pipeline_returns_artifacts(self) -> None:
        result = run_output_pipeline(
            plugin_name="quarto-portfolio-report",
            plugins_dir="plugins",
            portfolio_path="tests/fixtures/portfolio.json",
            snapshots_path="tests/fixtures/snapshots.jsonl",
            output_dir="out/reports",
        )
        self.assertIn("artifacts", result)
        self.assertIsInstance(result["artifacts"], list)
        html_artifacts = [a for a in result["artifacts"] if a.get("type") == "html"]
        self.assertTrue(html_artifacts)
        self.assertTrue(Path(html_artifacts[0]["path"]).exists())


if __name__ == "__main__":
    unittest.main()

