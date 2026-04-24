from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
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


if __name__ == "__main__":
    unittest.main()
