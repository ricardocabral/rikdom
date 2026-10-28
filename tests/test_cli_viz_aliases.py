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


class CliVizAliasArtifactTests(unittest.TestCase):
    def test_aliases_generate_the_same_local_report_bundle_as_viz(self) -> None:
        import json
        from html.parser import HTMLParser

        class LocalLinks(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.links.extend(value for key, value in attrs if key == "href")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            totals = []
            cases = [
                ("viz", ["--out", str(root / "viz" / "dashboard.html")], root / "viz", "dashboard.html"),
                ("visualize", ["--out-dir", str(root / "visualize")], root / "visualize", "dashboard.html"),
                ("render-report", ["--out-dir", str(root / "legacy-unused"), "--out", str(root / "report" / "custom.html")], root / "report", "custom.html"),
            ]
            for command, flags, output, dashboard in cases:
                with self.subTest(command=command), patch.dict("os.environ", {"RIKDOM_DISABLE_QUARTO": "1"}):
                    errors = io.StringIO()
                    with redirect_stdout(io.StringIO()), redirect_stderr(errors):
                        code = main([
                            command, "--portfolio", "tests/fixtures/portfolio.json",
                            "--snapshots", "tests/fixtures/snapshots.jsonl",
                            "--plugins-dir", "plugins", *flags,
                        ])
                    self.assertEqual(code, 0, errors.getvalue())
                    self.assertEqual("deprecated" in errors.getvalue(), command != "viz")
                    self.assertFalse((root / "legacy-unused").exists())
                    payload = json.loads((output / "quarto-input.json").read_text())
                    totals.append(payload["sections"]["current_valuation"]["total_value_base"])
                    self.assertEqual(payload["sections"]["timeline"][-1]["portfolio_value_base"], 165830.0)
                    for filename in (dashboard, "portfolio-report.html"):
                        links = LocalLinks()
                        links.feed((output / filename).read_text())
                        self.assertGreaterEqual(len(links.links), 5)
                        for href in links.links:
                            self.assertTrue((output / href).is_file(), href)
                    self.assertIn("165830.0", (output / dashboard).read_text())
            self.assertEqual(totals, [165830.0] * 3)


if __name__ == "__main__":
    unittest.main()
