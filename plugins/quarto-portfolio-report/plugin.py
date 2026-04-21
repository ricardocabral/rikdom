from __future__ import annotations

import json
import math
import os
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


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            amount = float(text)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(amount):
        return None
    return amount


def _to_base_amount(holding: dict[str, Any], amount: float, currency: str, base_currency: str) -> float | None:
    if currency == base_currency:
        return amount
    metadata = holding.get("metadata")
    fx_rate = _safe_float(metadata.get("fx_rate_to_base")) if isinstance(metadata, dict) else None
    if fx_rate is None or fx_rate <= 0:
        return None
    return amount * fx_rate


def _asset_type_to_class(asset_type_catalog: Any) -> dict[str, str]:
    index: dict[str, str] = {}
    if not isinstance(asset_type_catalog, list):
        return index
    for item in asset_type_catalog:
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("id", "")).strip()
        asset_class = str(item.get("asset_class", "")).strip()
        if asset_id and asset_class:
            index[asset_id] = asset_class
    return index


def _asset_type_bucket(asset_type_id: str, asset_class: str) -> str:
    if asset_type_id == "debt_instrument":
        return "debt_instrument"
    if asset_class == "debt":
        return "debt_instrument"
    return asset_type_id or "unknown"


def _build_report_payload(portfolio: dict[str, Any], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    settings = portfolio.get("settings", {})
    profile = portfolio.get("profile", {})
    holdings = portfolio.get("holdings", [])
    asset_type_catalog = portfolio.get("asset_type_catalog", [])
    asset_type_classes = _asset_type_to_class(asset_type_catalog)
    base_currency = str(settings.get("base_currency", "USD")).upper().strip() or "USD"

    by_currency: dict[str, float] = {}
    by_asset_type: dict[str, float] = {}
    geo: dict[str, float] = {}
    for holding in holdings if isinstance(holdings, list) else []:
        if not isinstance(holding, dict):
            continue
        market_value = holding.get("market_value", {})
        if not isinstance(market_value, dict):
            continue
        amount = _safe_float(market_value.get("amount"))
        if amount is None:
            continue
        currency = str(market_value.get("currency", "")).upper().strip() or "UNKNOWN"
        by_currency[currency] = by_currency.get(currency, 0.0) + amount

        asset_type_id = str(holding.get("asset_type_id", "")).strip()
        asset_class = asset_type_classes.get(asset_type_id, "")
        bucket = _asset_type_bucket(asset_type_id, asset_class)
        amount_base = _to_base_amount(holding, amount, currency, base_currency)
        if amount_base is None:
            continue
        by_asset_type[bucket] = by_asset_type.get(bucket, 0.0) + amount_base

        jurisdiction = holding.get("jurisdiction", {})
        country = ""
        if isinstance(jurisdiction, dict):
            country = str(jurisdiction.get("country", "")).upper().strip()
        if not country:
            country = str(profile.get("country", "")).upper().strip() or "UNKNOWN"
        geo[country] = geo.get(country, 0.0) + amount_base

    top_holdings = []
    for holding in holdings if isinstance(holdings, list) else []:
        if not isinstance(holding, dict):
            continue
        market_value = holding.get("market_value", {})
        amount = 0.0
        currency = base_currency
        if isinstance(market_value, dict):
            parsed_amount = _safe_float(market_value.get("amount"))
            if parsed_amount is not None:
                amount = parsed_amount
            currency = str(market_value.get("currency", currency)).upper().strip() or currency
        top_holdings.append(
            {
                "id": str(holding.get("id", "")),
                "label": str(holding.get("label", "")),
                "amount": amount,
                "currency": currency,
            }
        )
    top_holdings = sorted(top_holdings, key=lambda item: item["amount"], reverse=True)[:5]

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
            "base_currency": base_currency,
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
    if os.environ.get("RIKDOM_DISABLE_QUARTO"):
        return None
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
