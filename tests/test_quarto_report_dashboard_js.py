from __future__ import annotations

import unittest
from pathlib import Path

DASHBOARD_TEMPLATE_PATH = Path(
    "plugins/quarto-portfolio-report/templates/dashboard.qmd"
)


class DashboardJsSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")

    @staticmethod
    def _skip_js_string(source: str, start: int, quote: str) -> int:
        i = start + 1
        while i < len(source):
            if source[i] == "\\":
                i += 2
                continue
            if source[i] == quote:
                return i + 1
            i += 1
        return i

    @classmethod
    def _skip_js_expression(cls, source: str, start: int) -> int:
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            ch = source[i]
            if ch in ("'", '"'):
                i = cls._skip_js_string(source, i, ch)
                continue
            if ch == "`":
                _, i = cls._extract_template_interpolations(source, i)
                continue
            if ch == "{":
                depth += 1
                i += 1
                continue
            if ch == "}":
                depth -= 1
                i += 1
                continue
            if ch == "\\":
                i += 2
                continue
            i += 1
        return i

    @classmethod
    def _extract_template_interpolations(
        cls, source: str, start_backtick: int
    ) -> tuple[list[str], int]:
        assert source[start_backtick] == "`"
        i = start_backtick + 1
        expressions: list[str] = []
        while i < len(source):
            ch = source[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                return expressions, i + 1
            if ch == "$" and i + 1 < len(source) and source[i + 1] == "{":
                expr_start = i + 2
                expr_end = cls._skip_js_expression(source, expr_start)
                expressions.append(source[expr_start : expr_end - 1].strip())
                i = expr_end
                continue
            i += 1
        return expressions, i

    @classmethod
    def _all_innerhtml_interpolations(cls) -> list[str]:
        source = cls.source
        expressions: list[str] = []
        i = 0
        needle = ".innerHTML"

        while True:
            idx = source.find(needle, i)
            if idx == -1:
                break

            eq = source.find("=", idx + len(needle))
            if eq == -1:
                break

            cursor = eq + 1
            while cursor < len(source) and source[cursor].isspace():
                cursor += 1

            if cursor < len(source) and source[cursor] == "`":
                template_expressions, next_index = cls._extract_template_interpolations(
                    source, cursor
                )
                expressions.extend(template_expressions)
                i = next_index
                continue

            i = cursor + 1

        return expressions

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

        interpolations = self._all_innerhtml_interpolations()
        self.assertGreater(
            len(interpolations),
            0,
            "No innerHTML template interpolations found; expected at least one safety contract target.",
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

        for expression in interpolations:
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
        self.assertIn("const escapeHtml", self.source)
        for replacement in (
            ".replace(/&/g, '&amp;')",
            ".replace(/</g, '&lt;')",
            ".replace(/>/g, '&gt;')",
            ".replace(/\"/g, '&quot;')",
            ".replace(/'/g, '&#39;')",
        ):
            self.assertIn(
                replacement,
                self.source,
                f"escapeHtml missing replacement step: {replacement}",
            )


if __name__ == "__main__":
    unittest.main()
