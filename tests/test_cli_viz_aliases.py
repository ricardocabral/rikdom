from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from rikdom.cli import build_parser


class CliVizAliasTests(unittest.TestCase):
    """The `visualize` and `render-report` subcommands are deprecated
    aliases for `viz`. They must continue to resolve to `cmd_viz` and
    emit a deprecation warning for at least one transition release."""

    def test_visualize_alias_is_registered_and_dispatches_to_cmd_viz(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "visualize",
                "--data-dir",
                "data",
                "--out-root",
                "out",
            ]
        )
        from rikdom.cli import cmd_viz  # imported here to avoid circulars

        captured_err = io.StringIO()
        with (
            patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
            redirect_stderr(captured_err),
            redirect_stdout(io.StringIO()),
        ):
            rc = args.func(args)

        self.assertEqual(rc, 0)
        mock_viz.assert_called_once_with(args)
        self.assertIn("deprecated", captured_err.getvalue().lower())
        # Sanity: the original cmd_viz symbol still exists.
        self.assertTrue(callable(cmd_viz))

    def test_render_report_alias_is_registered_and_dispatches_to_cmd_viz(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "render-report",
                "--data-dir",
                "data",
                "--out-root",
                "out",
            ]
        )

        captured_err = io.StringIO()
        with (
            patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
            redirect_stderr(captured_err),
            redirect_stdout(io.StringIO()),
        ):
            rc = args.func(args)

        self.assertEqual(rc, 0)
        mock_viz.assert_called_once_with(args)
        self.assertIn("deprecated", captured_err.getvalue().lower())

    def test_render_report_alias_maps_legacy_out_dir_to_dashboard_out(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "render-report",
                "--out-dir",
                "legacy-out",
            ]
        )

        with (
            patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
            redirect_stderr(io.StringIO()),
            redirect_stdout(io.StringIO()),
        ):
            rc = args.func(args)

        self.assertEqual(rc, 0)
        mock_viz.assert_called_once_with(args)
        self.assertEqual(args.out, str(Path("legacy-out") / "dashboard.html"))

    def test_render_report_alias_forwards_legacy_plugin_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            plugins_dir = tmp_path / "plugins-custom"
            parser = build_parser()
            args = parser.parse_args(
                [
                    "render-report",
                    "--portfolio",
                    str(tmp_path / "portfolio.json"),
                    "--snapshots",
                    str(tmp_path / "snapshots.jsonl"),
                    "--fx-history",
                    str(tmp_path / "fx.json"),
                    "--out-dir",
                    str(out_dir),
                    "--plugin",
                    "custom-report-plugin",
                    "--plugins-dir",
                    str(plugins_dir),
                ]
            )

            def fake_pipeline(**kwargs):
                dashboard = out_dir / "dashboard.html"
                dashboard.parent.mkdir(parents=True, exist_ok=True)
                dashboard.write_text("<html></html>", encoding="utf-8")
                return {
                    "artifacts": [{"type": "html_dashboard", "path": str(dashboard)}]
                }

            with (
                patch(
                    "rikdom.cli.run_output_pipeline", side_effect=fake_pipeline
                ) as mock_pipeline,
                redirect_stderr(io.StringIO()),
                redirect_stdout(io.StringIO()),
            ):
                rc = args.func(args)

            self.assertEqual(rc, 0)
            mock_pipeline.assert_called_once_with(
                plugin_name="custom-report-plugin",
                plugins_dir=str(plugins_dir),
                portfolio_path=str(tmp_path / "portfolio.json"),
                snapshots_path=str(tmp_path / "snapshots.jsonl"),
                output_dir=str(out_dir.resolve()),
            )


if __name__ == "__main__":
    unittest.main()
