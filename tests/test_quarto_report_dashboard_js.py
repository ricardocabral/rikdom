from __future__ import annotations

import re
import unittest
from pathlib import Path

PLUGIN_PATH = Path("plugins/quarto-portfolio-report/plugin.py")


class DashboardJsSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PLUGIN_PATH.read_text(encoding="utf-8")

    def test_fmt_compact_uses_intl_compact_notation(self) -> None:
        """Threshold promotion must be handled by Intl, not hand-rolled K/M/B.

        A hand-rolled scaler like ``999_500 -> 1000K`` rounds before deciding
        the suffix and can cross the next threshold without promoting it.
        """
        self.assertIn("notation: 'compact'", self.source)
        self.assertNotRegex(
            self.source,
            r"suffix\s*=\s*'K'",
            msg="Hand-rolled K/M/B suffix logic resurfaced — use Intl notation:'compact'.",
        )

    def test_currency_code_is_strictly_validated(self) -> None:
        self.assertRegex(self.source, r"CCY_RE\s*=\s*/\^\[A-Z\]\{3\}\$/")
        self.assertIn("const safeCcy", self.source)

    def test_escape_html_is_defined_and_used(self) -> None:
        self.assertIn("const escapeHtml", self.source)
        # Dynamic interpolations in innerHTML SVG templates must go through escapeHtml.
        expected = [
            "escapeHtml(t.label)",
            "escapeHtml(formatYm(",
            "escapeHtml(centerLabel)",
            "escapeHtml(fmtCompact(total",
            "escapeHtml(slice.label)",
            "escapeHtml(formatValue(slice))",
            "escapeHtml(slice.color)",
        ]
        for pattern in expected:
            self.assertIn(pattern, self.source, f"Missing escape for {pattern!r}")

    def test_escape_html_covers_all_xss_vectors(self) -> None:
        match = re.search(
            r"const escapeHtml = \(value\) => String\(.*?\)(?P<chain>(?:\s*\.replace\([^)]*\))+)",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "escapeHtml function not found")
        chain = match.group("chain")
        for needle in ("/&/g", "/</g", "/>/g", "/\\\"/g", "/'/g"):
            self.assertIn(needle, chain, f"escapeHtml missing replacement for {needle}")


if __name__ == "__main__":
    unittest.main()
