from __future__ import annotations

import re
import unittest
from pathlib import Path

DASHBOARD_TEMPLATE_PATH = Path(
    "plugins/quarto-portfolio-report/templates/dashboard.qmd"
)


class DashboardJsSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_fmt_compact_uses_intl_compact_notation(self) -> None:
        """Threshold promotion must be delegated to Intl compact notation."""
        self.assertRegex(self.source, r"notation\s*:\s*['\"]compact['\"]")
        self.assertNotRegex(
            self.source,
            r"suffix\s*=\s*['\"][KMB]['\"]",
            msg="Hand-rolled K/M/B suffix logic resurfaced — use Intl compact notation.",
        )

    def test_currency_code_is_strictly_validated(self) -> None:
        self.assertRegex(self.source, r"CCY_RE\s*=\s*/\^\[A-Z\]\{3\}\$/")
        self.assertRegex(self.source, r"const\s+safeCcy\s*=")

    def test_escape_html_is_defined_and_used_for_all_innerhtml_interpolations(
        self,
    ) -> None:
        self.assertIn("const escapeHtml", self.source)

        innerhtml_templates = re.findall(
            r"\.innerHTML\s*=\s*`(?P<template>.*?)`",
            self.source,
            re.DOTALL,
        )
        self.assertGreater(
            len(innerhtml_templates),
            0,
            "No innerHTML template literals found; expected at least one safety contract target.",
        )

        allowlist = (
            "padLeft",
            "padRight",
            "padTop",
            "padBottom",
            "W",
            "H",
            "cx",
            "cy",
            "r",
            "strokeW",
            "offset",
            "dash",
            "circumference",
            "xFor(",
            "yFor(",
            "toFixed(",
            "s.piece",
        )

        for template in innerhtml_templates:
            for expr in re.findall(r"\$\{([^}]+)\}", template):
                expression = expr.strip()
                if "escapeHtml(" in expression:
                    continue
                if any(token in expression for token in allowlist):
                    continue
                self.fail(
                    f"Unescaped innerHTML interpolation found: ${{{expression}}}. "
                    "Wrap non-numeric interpolations with escapeHtml(...)."
                )

        for required in (
            "escapeHtml(t.label)",
            "escapeHtml(formatYm(",
            "escapeHtml(centerLabel)",
            "escapeHtml(fmtCompact(total",
            "escapeHtml(slice.label)",
            "escapeHtml(pct(slice.value, total))",
            "escapeHtml(formatValue(slice))",
            "escapeHtml(slice.color)",
        ):
            self.assertIn(required, self.source, f"Missing escape for {required!r}")

    def test_escape_html_covers_all_xss_vectors(self) -> None:
        match = re.search(
            r"const escapeHtml = \(value\) => String\(.*?\)(?P<chain>(?:\s*\.replace\([^)]*\))+)",
            self.source,
            re.DOTALL,
        )
        if match is None:
            self.fail("escapeHtml function not found")
            return
        chain = match.group("chain")
        for pattern in (r"/&/g", r"/</g", r"/>/g", r"/\\?\"/g", r"/'/g"):
            self.assertRegex(
                chain, pattern, f"escapeHtml missing replacement for pattern {pattern}"
            )


if __name__ == "__main__":
    unittest.main()
