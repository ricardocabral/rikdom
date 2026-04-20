from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path
from typing import Any

from rikdom.plugin_engine.hookspecs import hookimpl
from rikdom.storage import load_json, load_jsonl

QUARTO_TIMEOUT_SECONDS = 120
REPORT_FILENAME = "portfolio-report.html"


def _build_report_payload(portfolio: dict[str, Any], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    settings = portfolio.get("settings", {})
    profile = portfolio.get("profile", {})
    holdings = portfolio.get("holdings", [])
    asset_type_catalog = portfolio.get("asset_type_catalog", [])

    by_currency: dict[str, float] = {}
    by_asset_type: dict[str, float] = {}
    geo: dict[str, float] = {}
    for holding in holdings if isinstance(holdings, list) else []:
        if not isinstance(holding, dict):
            continue
        market_value = holding.get("market_value", {})
        if not isinstance(market_value, dict):
            continue
        amount = market_value.get("amount")
        currency = str(market_value.get("currency", "")).upper().strip()
        if not isinstance(amount, (int, float)):
            continue
        by_currency[currency] = by_currency.get(currency, 0.0) + float(amount)

        asset_type_id = str(holding.get("asset_type_id", "")).strip() or "unknown"
        by_asset_type[asset_type_id] = by_asset_type.get(asset_type_id, 0.0) + float(amount)

        jurisdiction = holding.get("jurisdiction", {})
        country = ""
        if isinstance(jurisdiction, dict):
            country = str(jurisdiction.get("country", "")).upper().strip()
        if not country:
            country = str(profile.get("country", "")).upper().strip() or "UNKNOWN"
        geo[country] = geo.get(country, 0.0) + float(amount)

    top_holdings = sorted(
        [
            {
                "id": str(h.get("id", "")),
                "label": str(h.get("label", "")),
                "amount": float(h.get("market_value", {}).get("amount", 0.0))
                if isinstance(h.get("market_value"), dict)
                else 0.0,
            }
            for h in holdings
            if isinstance(h, dict)
        ],
        key=lambda item: item["amount"],
        reverse=True,
    )[:5]

    timeline = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        totals = snapshot.get("totals", {})
        if not isinstance(totals, dict):
            continue
        value = totals.get("portfolio_value_base")
        if not isinstance(value, (int, float)):
            continue
        timeline.append(
            {
                "timestamp": snapshot.get("timestamp"),
                "portfolio_value_base": float(value),
                "by_asset_class": totals.get("by_asset_class", {}),
            }
        )

    return {
        "profile": {
            "display_name": profile.get("display_name", "Portfolio"),
            "country": profile.get("country"),
            "base_currency": settings.get("base_currency", "USD"),
            "timezone": settings.get("timezone"),
        },
        "asset_type_catalog": asset_type_catalog,
        "sections": {
            "timeline": timeline,
            "currency_split": by_currency,
            "asset_type_breakdown": by_asset_type,
            "geography": geo,
            "risk": {
                "top_holdings": top_holdings,
                "fx_non_base_share_hint": "computed from currency_split vs base_currency",
            },
        },
    }


def _write_fallback_html(path: Path, reason: str) -> None:
    path.write_text(
        (
            "<html><body>"
            "<h1>Fallback Portfolio Report</h1>"
            f"<p>{escape(reason)}</p>"
            "</body></html>"
        ),
        encoding="utf-8",
    )


def _render_with_quarto(template_dir: Path, out_dir: Path) -> tuple[bool, str | None]:
    quarto_bin = _find_quarto_bin()
    if not quarto_bin:
        return False, "Quarto binary 'quarto' not found in PATH. Generated fallback HTML artifact."

    command = [
        quarto_bin,
        "render",
        "report.qmd",
        "--to",
        "html",
        "--output",
        REPORT_FILENAME,
        "--output-dir",
        str(out_dir),
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(template_dir),
            text=True,
            capture_output=True,
            check=False,
            timeout=QUARTO_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            f"Quarto render timed out after {QUARTO_TIMEOUT_SECONDS}s. Generated fallback HTML artifact.",
        )
    except OSError as exc:
        return False, f"Quarto execution error: {exc}. Generated fallback HTML artifact."

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if detail:
            return (
                False,
                f"Quarto render failed: {detail}. Generated fallback HTML artifact.",
            )
        return False, "Quarto render failed with non-zero exit code. Generated fallback HTML artifact."

    return True, None


def _find_quarto_bin() -> str | None:
    # First try PATH.
    quarto_bin = shutil.which("quarto")
    if quarto_bin:
        return quarto_bin

    # Then try common Python env bin locations (uv/venv/asdf symlink layouts).
    exe_parent = Path(sys.executable).parent
    prefix_bin = Path(sys.prefix) / "bin"
    base_prefix_bin = Path(sys.base_prefix) / "bin"
    resolved_parent = Path(sys.executable).resolve().parent
    candidates = [
        exe_parent / "quarto",
        exe_parent / "quarto.exe",
        prefix_bin / "quarto",
        prefix_bin / "quarto.exe",
        base_prefix_bin / "quarto",
        base_prefix_bin / "quarto.exe",
        resolved_parent / "quarto",
        resolved_parent / "quarto.exe",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None


def _prepare_render_workspace(
    templates_dir: Path,
    payload: dict[str, Any],
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    tmp_dir = tempfile.TemporaryDirectory()
    render_dir = Path(tmp_dir.name)

    for source in templates_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, render_dir / source.name)

    data_js = render_dir / "report-data.js"
    data_js.write_text(
        "window.RIKDOM_REPORT_DATA = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    return tmp_dir, render_dir


class Plugin:
    @hookimpl
    def output(self, ctx, request):
        portfolio = load_json(request.portfolio_path)
        snapshots = load_jsonl(request.snapshots_path)
        out_dir = Path(request.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        payload = _build_report_payload(portfolio, snapshots)
        payload_path = out_dir / "quarto-input.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        output_js_path = out_dir / "report-data.js"
        output_js_path.write_text(
            "window.RIKDOM_REPORT_DATA = "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + ";\n",
            encoding="utf-8",
        )

        warnings: list[str] = []
        html_path = out_dir / REPORT_FILENAME
        templates_dir = Path(__file__).resolve().parent / "templates"
        report_template_path = templates_dir / "report.qmd"

        if not report_template_path.exists():
            warning = f"Missing Quarto template: {report_template_path}. Generated fallback HTML artifact."
            warnings.append(warning)
            _write_fallback_html(html_path, warning)
        else:
            tmp_dir, render_dir = _prepare_render_workspace(templates_dir, payload)
            try:
                rendered, warning = _render_with_quarto(render_dir, out_dir.resolve())
                if rendered:
                    source_js = render_dir / "report-data.js"
                    if source_js.exists() and not output_js_path.exists():
                        shutil.copy2(source_js, output_js_path)
            finally:
                tmp_dir.cleanup()

            if warning:
                warnings.append(warning)
            if not rendered:
                _write_fallback_html(html_path, warnings[-1])

        if not html_path.exists():
            warning = (
                f"Expected report artifact was not created: {html_path}. "
                "Generated fallback HTML artifact."
            )
            warnings.append(warning)
            _write_fallback_html(html_path, warning)

        return {
            "plugin": "quarto-portfolio-report",
            "artifacts": [
                {"type": "html", "path": str(html_path)},
                {"type": "json", "path": str(payload_path)},
                {"type": "js", "path": str(output_js_path)},
            ],
            "warnings": warnings,
        }
