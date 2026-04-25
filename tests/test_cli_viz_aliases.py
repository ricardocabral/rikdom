from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from rikdom.cli import main


class CliVizAliasTests(unittest.TestCase):
    """The `visualize` and `render-report` subcommands are deprecated
    aliases for `viz`. They must continue to resolve to `cmd_viz` and
    emit a deprecation warning for at least one transition release."""

    def test_visualize_alias_is_registered_and_dispatches_to_cmd_viz(self) -> None:
        from rikdom.cli import cmd_viz  # imported here to avoid circulars

        captured_err = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
            redirect_stderr(captured_err),
            redirect_stdout(io.StringIO()),
        ):
            tmp_path = Path(tmp)
            rc = main(
                [
                    "visualize",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--out-root",
                    str(tmp_path / "out"),
                ]
            )

        self.assertEqual(rc, 0)
        mock_viz.assert_called_once()
        called_args = mock_viz.call_args.args[0]
        self.assertEqual(called_args.command, "visualize")
        self.assertIn("deprecated", captured_err.getvalue().lower())
        # Sanity: the original cmd_viz symbol still exists.
        self.assertTrue(callable(cmd_viz))

    def test_render_report_alias_is_registered_and_dispatches_to_cmd_viz(self) -> None:
        captured_err = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
            redirect_stderr(captured_err),
            redirect_stdout(io.StringIO()),
        ):
            tmp_path = Path(tmp)
            rc = main(
                [
                    "render-report",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--out-root",
                    str(tmp_path / "out"),
                ]
            )

        self.assertEqual(rc, 0)
        mock_viz.assert_called_once()
        called_args = mock_viz.call_args.args[0]
        self.assertEqual(called_args.command, "render-report")
        self.assertIn("deprecated", captured_err.getvalue().lower())

    def test_render_report_alias_maps_legacy_out_dir_to_dashboard_out(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
            redirect_stderr(io.StringIO()),
            redirect_stdout(io.StringIO()),
        ):
            tmp_path = Path(tmp)
            legacy_out = tmp_path / "legacy-out"
            rc = main(
                [
                    "render-report",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--out-root",
                    str(tmp_path / "out"),
                    "--out-dir",
                    str(legacy_out),
                ]
            )

        self.assertEqual(rc, 0)
        mock_viz.assert_called_once()
        called_args = mock_viz.call_args.args[0]
        self.assertEqual(called_args.out, str(legacy_out / "dashboard.html"))

    def test_deprecated_aliases_map_explicit_out_dir_after_workspace_defaults(
        self,
    ) -> None:
        for alias in ("render-report", "visualize"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                legacy_out = tmp_path / "legacy-out"

                with (
                    patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
                    redirect_stderr(io.StringIO()),
                    redirect_stdout(io.StringIO()),
                ):
                    rc = main(
                        [
                            alias,
                            "--data-dir",
                            str(tmp_path / "data"),
                            "--out-root",
                            str(tmp_path / "out"),
                            "--out-dir",
                            str(legacy_out),
                        ]
                    )

                self.assertEqual(rc, 0)
                mock_viz.assert_called_once()
                called_args = mock_viz.call_args.args[0]
                self.assertEqual(called_args.out, str(legacy_out / "dashboard.html"))

    def test_deprecated_alias_explicit_out_takes_precedence_over_out_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            explicit_out = tmp_path / "custom.html"
            legacy_out = tmp_path / "legacy-out"

            with (
                patch("rikdom.cli.cmd_viz", return_value=0) as mock_viz,
                redirect_stderr(io.StringIO()),
                redirect_stdout(io.StringIO()),
            ):
                rc = main(
                    [
                        "render-report",
                        "--data-dir",
                        str(tmp_path / "data"),
                        "--out-root",
                        str(tmp_path / "out"),
                        "--out-dir",
                        str(legacy_out),
                        "--out",
                        str(explicit_out),
                    ]
                )

            self.assertEqual(rc, 0)
            mock_viz.assert_called_once()
            called_args = mock_viz.call_args.args[0]
            self.assertEqual(called_args.out, str(explicit_out))

    def test_render_report_alias_forwards_legacy_plugin_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            plugins_dir = tmp_path / "plugins-custom"

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
                rc = main(
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
