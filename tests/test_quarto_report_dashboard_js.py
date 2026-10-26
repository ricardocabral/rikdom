from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
import unittest
from pathlib import Path

DASHBOARD_TEMPLATE_PATH = Path(
    "plugins/quarto-portfolio-report/templates/dashboard.qmd"
)


def run_template(source: str, payload: dict) -> dict:
    """Execute the real application script and capture the HTML it emits."""
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("Node.js is required for report JavaScript checks")
    runner = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const scripts = [...input.source.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const script = scripts.find(s => s.includes('const payload = window.RIKDOM_REPORT_DATA'));
if (!script) throw new Error('Application script missing');
const nodes = {};
const document = {documentElement: {}, getElementById(id) {
    return nodes[id] ||= {innerHTML: '', textContent: ''};
}};
vm.runInNewContext(script, {window: {RIKDOM_REPORT_DATA: input.payload}, document,
    getComputedStyle: () => ({getPropertyValue: () => ''}), Intl, Date});
process.stdout.write(JSON.stringify(nodes));
"""
    completed = subprocess.run(
        [node, "-e", runner], input=json.dumps({"source": source, "payload": payload}),
        text=True, capture_output=True, timeout=10, check=True,
    )
    return json.loads(completed.stdout)


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
    def _extract_js_expression(
        cls, source: str, start: int
    ) -> tuple[str, list[str], int]:
        depth = 1
        i = start
        nested_interpolations: list[str] = []
        while i < len(source) and depth > 0:
            ch = source[i]
            if ch in ("'", '"'):
                i = cls._skip_js_string(source, i, ch)
                continue
            if ch == "`":
                nested, i = cls._extract_template_interpolations(source, i)
                nested_interpolations.extend(nested)
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
        return source[start : i - 1].strip(), nested_interpolations, i

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
                expression, nested, expr_end = cls._extract_js_expression(
                    source, expr_start
                )
                expressions.append(expression)
                expressions.extend(nested)
                i = expr_end
                continue
            i += 1
        return expressions, i

    @staticmethod
    def _skip_js_line_comment(source: str, start: int) -> int:
        newline = source.find("\n", start + 2)
        return len(source) if newline == -1 else newline + 1

    @staticmethod
    def _skip_js_block_comment(source: str, start: int) -> int:
        end = source.find("*/", start + 2)
        return len(source) if end == -1 else end + 2

    @classmethod
    def _extract_assignment_interpolations(
        cls, source: str, start: int
    ) -> tuple[list[str], int]:
        expressions: list[str] = []
        i = start
        depth = 0
        openers = {"(": ")", "{": "}", "[": "]"}
        closers = set(openers.values())
        while i < len(source):
            ch = source[i]
            next_ch = source[i + 1] if i + 1 < len(source) else ""
            if ch == "/" and next_ch == "/":
                i = cls._skip_js_line_comment(source, i)
                continue
            if ch == "/" and next_ch == "*":
                i = cls._skip_js_block_comment(source, i)
                continue
            if ch in ("'", '"'):
                i = cls._skip_js_string(source, i, ch)
                continue
            if ch == "`":
                nested, i = cls._extract_template_interpolations(source, i)
                expressions.extend(nested)
                continue
            if ch in openers:
                depth += 1
                i += 1
                continue
            if ch in closers:
                depth = max(depth - 1, 0)
                i += 1
                continue
            if ch == ";" and depth == 0:
                return expressions, i + 1
            i += 1
        return expressions, i

    @classmethod
    def _is_wrapped_by_escape_html(cls, expression: str) -> bool:
        if not expression.startswith("escapeHtml("):
            return False

        depth = 0
        i = len("escapeHtml")
        while i < len(expression):
            ch = expression[i]
            if ch in ("'", '"'):
                i = cls._skip_js_string(expression, i, ch)
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return expression[i + 1 :].strip() == ""
            i += 1
        return False

    @classmethod
    def _is_allowlisted_innerhtml_expression(cls, expression: str) -> bool:
        numeric_identifiers = {
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
        }
        arithmetic_terms = "|".join(sorted(numeric_identifiers))
        numeric_patterns = (
            rf"^(?:{arithmetic_terms})$",
            rf"^(?:{arithmetic_terms})\s*[-+]\s*(?:\d+|{arithmetic_terms})$",
            rf"^\((?:t\.y|{arithmetic_terms})\s*[-+]\s*\d+\)\.toFixed\(\d+\)$",
            r"^(?:t\.y|xFor\([^`]*\)|yFor\([^`]*\))\.toFixed\(\d+\)$",
        )
        template_fragment_container_patterns = (
            r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\.map\([^`]*=>\s*`.*`\)\.join\(''\)$",
        )
        explicitly_safe_html_fragments = ("slices.map(s => s.piece).join('')",)
        return (
            expression in explicitly_safe_html_fragments
            or any(re.fullmatch(pattern, expression) for pattern in numeric_patterns)
            or any(
                re.fullmatch(pattern, expression, flags=re.DOTALL)
                for pattern in template_fragment_container_patterns
            )
        )

    @classmethod
    def _escape_html_body(cls) -> str:
        match = re.search(
            r"const\s+escapeHtml\s*=\s*\([^)]*\)\s*=>\s*",
            cls.source,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("const escapeHtml arrow function was not found")

        start = match.end()
        body_lines: list[str] = []
        for line in cls.source[start:].splitlines():
            body_lines.append(line)
            if line.rstrip().endswith(";"):
                return "\n".join(body_lines).rstrip()[:-1]
        raise AssertionError("const escapeHtml declaration is missing a terminator")

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

            assignment_expressions, next_index = cls._extract_assignment_interpolations(
                source, cursor
            )
            expressions.extend(assignment_expressions)
            i = next_index

        return expressions

    def test_template_parser_preserves_outer_and_nested_interpolations(self) -> None:
        expressions, end = self._extract_template_interpolations(
            "`value ${unsafe + `${escapeHtml(safe)}`}`",
            0,
        )

        self.assertEqual(end, len("`value ${unsafe + `${escapeHtml(safe)}`}`"))
        self.assertIn("unsafe + `${escapeHtml(safe)}`", expressions)
        self.assertIn("escapeHtml(safe)", expressions)

    def test_assignment_parser_ignores_nested_and_commented_semicolons(self) -> None:
        source = """
          (`ignored ;` + /* ; */ `${escapeHtml(first)}` + ({ label: ';' }).label);
          next.innerHTML = `${second}`;
        """

        expressions, end = self._extract_assignment_interpolations(source, 0)

        self.assertIn("escapeHtml(first)", expressions)
        self.assertNotIn("second", expressions)
        self.assertEqual(end, source.index(");\n") + 2)

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

    def test_quality_fields_render_untrusted_text_without_html_injection(self) -> None:
        attack = '<img src=x onerror="alert(1)"> & unsafe'
        nodes = run_template(self.source, {
            "profile": {"display_name": attack, "base_currency": "EUR"},
            "sections": {"current_valuation": {"total_value_base": 26, "by_asset_class": {}},
                         "data_quality": {
                             "coverage": {"status": attack, "by_status": {attack: 1}},
                             "warnings": [attack], "excluded_holding_ids": [attack],
                             "artifacts": [{"label": attack, "href": 'reconciliation.json" onerror="alert(1)'}],
                         }},
        })
        html = nodes["data-quality"]["innerHTML"]
        self.assertIn("&lt;img", html)
        self.assertNotIn("<img", html)
        self.assertIn("26.00", nodes["total"]["textContent"])
        self.assertIn(attack, nodes["subtitle"]["textContent"])

        class Attributes(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.attrs = dict(attrs)
        parsed = Attributes()
        parsed.feed(html)
        self.assertNotIn("onerror", parsed.attrs)
        self.assertEqual(parsed.attrs["href"], 'reconciliation.json" onerror="alert(1)')

    def test_escape_html_covers_all_xss_vectors(self) -> None:
        escape_html_body = self._escape_html_body()
        for replacement in (
            ".replace(/&/g, '&amp;')",
            ".replace(/</g, '&lt;')",
            ".replace(/>/g, '&gt;')",
            ".replace(/\"/g, '&quot;')",
            ".replace(/'/g, '&#39;')",
        ):
            self.assertIn(
                replacement,
                escape_html_body,
                f"escapeHtml missing replacement step: {replacement}",
            )

    def test_chart_palette_is_theme_aware_via_css_vars(self) -> None:
        """Chart palette must read CSS variables so light/dark themes
        propagate to slices/legends. Hard-coded hex literals in the
        palette array would silently break theme support."""
        # Helper that reads CSS vars must exist.
        self.assertRegex(
            self.source,
            r"const\s+cssVar\s*=",
            msg="dashboard.qmd must declare a cssVar(...) helper",
        )
        # Each of the 8 chart slots must resolve through cssVar('--chart-N', ...).
        for n in range(1, 9):
            self.assertRegex(
                self.source,
                rf"cssVar\(\s*['\"]--chart-{n}['\"]",
                msg=f"chart palette slot {n} must come from CSS var --chart-{n}",
            )
        # Both light and dark themes must define the palette CSS vars.
        light_block = self.source.split("@media (prefers-color-scheme: dark)")[0]
        dark_split = self.source.split("@media (prefers-color-scheme: dark)")
        self.assertEqual(
            len(dark_split),
            2,
            msg="dashboard.qmd must define a dark-theme media query",
        )
        dark_block = dark_split[1]
        for n in range(1, 9):
            self.assertRegex(
                light_block,
                rf"--chart-{n}\s*:",
                msg=f"light theme missing --chart-{n} declaration",
            )
            self.assertRegex(
                dark_block,
                rf"--chart-{n}\s*:",
                msg=f"dark theme missing --chart-{n} declaration",
            )


REPORT_TEMPLATE_PATH = Path("plugins/quarto-portfolio-report/templates/report.qmd")


class ReportTemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = REPORT_TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_chart_palette_is_theme_aware_via_css_vars(self) -> None:
        self.assertRegex(self.source, r"const\s+cssVar\s*=")
        for n in range(1, 9):
            self.assertRegex(
                self.source,
                rf"cssVar\(\s*['\"]--rk-chart-{n}['\"]",
                msg=f"report palette slot {n} must come from CSS var --rk-chart-{n}",
            )
        # Trend chart axis/line colors must also flow through CSS vars so
        # the SVG adapts to dark mode (previously hard-coded hex strings).
        for required in (
            r"cssVar\(\s*['\"]--rk-chart-axis['\"]",
            r"cssVar\(\s*['\"]--rk-chart-line['\"]",
        ):
            self.assertRegex(
                self.source,
                required,
                msg=f"report.qmd must source {required!r} from CSS var",
            )

    def test_top_holdings_table_rows_match_headers_and_show_core_base_value(self) -> None:
        nodes = run_template(self.source, {
            "profile": {"base_currency": "EUR"},
            "sections": {"current_valuation": {"total_value_base": 26},
                         "risk": {"top_holdings": [
                             {"id": "included", "amount": 1000, "currency": "JPY", "base_amount": 6},
                             {"id": "excluded", "amount": 50, "currency": "GBP", "base_amount": None, "excluded_reason": "fx_missing"},
                         ]}},
        })
        class Table(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows = []
                self.row = None
                self.in_cell = False
            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self.row = []
                if tag in ("td", "th") and self.row is not None:
                    self.row.append("")
                    self.in_cell = True
            def handle_endtag(self, tag):
                if tag in ("td", "th"):
                    self.in_cell = False
                if tag == "tr" and self.row is not None:
                    self.rows.append(self.row)
                    self.row = None
            def handle_data(self, data):
                if self.in_cell:
                    self.row[-1] += data
        table = Table()
        table.feed(nodes["rk-app"]["innerHTML"])
        header, included, excluded = table.rows
        self.assertIn("Current base amount", header)
        self.assertEqual(len(header), len(included))
        self.assertEqual(len(header), len(excluded))
        base_index = header.index("Current base amount")
        self.assertIn("6.00", included[base_index])
        self.assertIn("Excluded: fx_missing", excluded[base_index])


if __name__ == "__main__":
    unittest.main()
