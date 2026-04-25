from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from rikdom.plugin_engine.hookspecs import hookimpl
from rikdom.storage import load_json, load_jsonl

QUARTO_TIMEOUT_SECONDS = 120
REPORT_FILENAME = "portfolio-report.html"
QUICKVIEW_FILENAME = "dashboard.html"


def _normalize_currency_code(value: Any, *, fallback: str = "UNKNOWN") -> str:
    code = str(value or "").strip().upper()
    if len(code) == 3 and code.isascii() and code.isalpha():
        return code
    return fallback


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


def _to_base_amount(
    holding: dict[str, Any], amount: float, currency: str, base_currency: str
) -> float | None:
    if currency == base_currency:
        return amount
    metadata = holding.get("metadata")
    fx_rate = (
        _safe_float(metadata.get("fx_rate_to_base"))
        if isinstance(metadata, dict)
        else None
    )
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


def _latest_fx_rates_to_base(
    snapshots: list[dict[str, Any]],
    *,
    base_currency: str,
) -> dict[str, float]:
    for snapshot in reversed(snapshots):
        if not isinstance(snapshot, dict):
            continue
        metadata = snapshot.get("metadata")
        if not isinstance(metadata, dict):
            continue
        fx_lock = metadata.get("fx_lock")
        if not isinstance(fx_lock, dict):
            continue
        lock_base = str(fx_lock.get("base_currency", "")).strip().upper()
        if lock_base and lock_base != base_currency:
            continue
        raw_rates = fx_lock.get("rates_to_base")
        if not isinstance(raw_rates, dict):
            continue

        normalized: dict[str, float] = {}
        for currency, rate in raw_rates.items():
            code = str(currency).strip().upper()
            parsed = _safe_float(rate)
            if not code or parsed is None or parsed <= 0:
                continue
            normalized[code] = parsed
        if normalized:
            return normalized

    return {}


def _build_quickview_currency_split(
    holdings: list[dict[str, Any]],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
) -> dict[str, Any]:
    native: dict[str, float] = {}
    converted_base: dict[str, float] = {}
    missing_rates: set[str] = set()

    for holding in holdings:
        market_value = holding.get("market_value")
        if not isinstance(market_value, dict):
            continue

        amount = _safe_float(market_value.get("amount"))
        currency = _normalize_currency_code(market_value.get("currency"))
        if amount is None:
            continue

        native[currency] = native.get(currency, 0.0) + amount

        if currency == base_currency:
            converted_base[currency] = converted_base.get(currency, 0.0) + amount
            continue

        fx_rate = fx_rates_to_base.get(currency)
        if fx_rate is None or fx_rate <= 0:
            metadata = holding.get("metadata")
            fallback = (
                _safe_float(metadata.get("fx_rate_to_base"))
                if isinstance(metadata, dict)
                else None
            )
            if fallback is not None and fallback > 0:
                fx_rate = fallback

        if fx_rate is None or fx_rate <= 0:
            missing_rates.add(currency)
            continue

        converted_base[currency] = converted_base.get(currency, 0.0) + amount * fx_rate

    return {
        "native": {k: round(v, 2) for k, v in sorted(native.items())},
        "converted_base": {
            k: round(v, 2)
            for k, v in sorted(
                converted_base.items(), key=lambda item: (-item[1], item[0])
            )
        },
        "missing_rates": sorted(missing_rates),
    }


def _to_base_amount_with_rates(
    holding: dict[str, Any],
    *,
    amount: float,
    currency: str,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
) -> float | None:
    if currency == base_currency:
        return amount
    fx_rate = fx_rates_to_base.get(currency)
    if isinstance(fx_rate, (int, float)) and float(fx_rate) > 0:
        return amount * float(fx_rate)
    return _to_base_amount(holding, amount, currency, base_currency)


def _extract_asset_class_targets(portfolio: dict[str, Any]) -> dict[str, float]:
    candidates: list[Any] = [
        portfolio.get("target_allocation_by_asset_class"),
        portfolio.get("settings", {}).get("target_allocation_by_asset_class")
        if isinstance(portfolio.get("settings"), dict)
        else None,
        portfolio.get("metadata", {}).get("target_allocation_by_asset_class")
        if isinstance(portfolio.get("metadata"), dict)
        else None,
    ]
    raw: dict[str, float] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key, value in candidate.items():
            parsed = _safe_float(value)
            if parsed is None or parsed < 0:
                continue
            raw[str(key)] = parsed
        if raw:
            break

    if not raw:
        return {}

    total = sum(raw.values())
    if total > 1.5:
        normalized = {k: v / 100.0 for k, v in raw.items()}
    else:
        normalized = raw

    norm_total = sum(normalized.values())
    if norm_total <= 0:
        return {}

    return {k: round(v / norm_total, 6) for k, v in normalized.items() if v > 0}


def _maturity_bucket(maturity_date: str | None, *, reference_date: datetime) -> str:
    if not maturity_date:
        return "unknown"
    try:
        maturity = datetime.fromisoformat(maturity_date.strip()).date()
    except ValueError:
        return "unknown"
    years = (maturity - reference_date.date()).days / 365.25
    if years <= 1:
        return "<=1y"
    if years <= 3:
        return "1-3y"
    if years <= 5:
        return "3-5y"
    return ">5y"


def _build_report_payload(
    portfolio: dict[str, Any], snapshots: list[dict[str, Any]]
) -> dict[str, Any]:
    settings = portfolio.get("settings", {})
    profile = portfolio.get("profile", {})
    holdings = portfolio.get("holdings", [])
    normalized_holdings = (
        [h for h in holdings if isinstance(h, dict)]
        if isinstance(holdings, list)
        else []
    )

    asset_type_catalog = portfolio.get("asset_type_catalog", [])
    asset_type_classes = _asset_type_to_class(asset_type_catalog)
    base_currency = str(settings.get("base_currency", "USD")).upper().strip() or "USD"

    fx_rates_to_base = _latest_fx_rates_to_base(snapshots, base_currency=base_currency)

    by_currency: dict[str, float] = {}
    by_asset_type: dict[str, float] = {}
    geo: dict[str, float] = {}
    for holding in normalized_holdings:
        market_value = holding.get("market_value", {})
        if not isinstance(market_value, dict):
            continue
        amount = _safe_float(market_value.get("amount"))
        if amount is None:
            continue
        currency = _normalize_currency_code(market_value.get("currency"))
        by_currency[currency] = by_currency.get(currency, 0.0) + amount

        asset_type_id = str(holding.get("asset_type_id", "")).strip()
        asset_class = asset_type_classes.get(asset_type_id, "")
        bucket = _asset_type_bucket(asset_type_id, asset_class)
        amount_base = _to_base_amount_with_rates(
            holding,
            amount=amount,
            currency=currency,
            base_currency=base_currency,
            fx_rates_to_base=fx_rates_to_base,
        )
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

    top_holdings: list[dict[str, Any]] = []
    for holding in normalized_holdings:
        market_value = holding.get("market_value", {})
        amount = 0.0
        currency = base_currency
        if isinstance(market_value, dict):
            parsed_amount = _safe_float(market_value.get("amount"))
            if parsed_amount is not None:
                amount = parsed_amount
            currency = _normalize_currency_code(
                market_value.get("currency"), fallback=currency
            )
        top_holdings.append(
            {
                "id": str(holding.get("id", "")),
                "label": str(holding.get("label", "")),
                "amount": amount,
                "currency": currency,
            }
        )
    top_holdings = sorted(top_holdings, key=lambda item: item["amount"], reverse=True)[
        :5
    ]

    timeline: list[dict[str, Any]] = []
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

    latest_by_asset_class: dict[str, float] = {}
    if timeline:
        maybe_latest = timeline[-1].get("by_asset_class")
        if isinstance(maybe_latest, dict):
            for key, value in maybe_latest.items():
                parsed = _safe_float(value)
                if parsed is not None and parsed > 0:
                    latest_by_asset_class[str(key)] = parsed

    quickview_currency = _build_quickview_currency_split(
        normalized_holdings,
        base_currency=base_currency,
        fx_rates_to_base=fx_rates_to_base,
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
            "quickview": {
                "latest_by_asset_class": latest_by_asset_class,
                "currency": quickview_currency,
            },
        },
    }


def _write_fallback_html(
    path: Path, reason: str, link_href: str, link_label: str
) -> None:
    path.write_text(
        (
            "<html><body>"
            "<h1>Fallback Portfolio Report</h1>"
            f"<p>{escape(reason)}</p>"
            f'<p><a href="{escape(link_href)}">{escape(link_label)}</a></p>'
            "</body></html>"
        ),
        encoding="utf-8",
    )


def _find_quarto_bin() -> str | None:
    if os.environ.get("RIKDOM_DISABLE_QUARTO"):
        return None
    quarto_bin = shutil.which("quarto")
    if quarto_bin:
        return quarto_bin

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


def _render_qmd(
    *,
    quarto_bin: str,
    render_dir: Path,
    out_dir: Path,
    template_name: str,
    output_name: str,
) -> tuple[bool, str | None]:
    command = [
        quarto_bin,
        "render",
        template_name,
        "--to",
        "html",
        "--output",
        output_name,
        "--output-dir",
        str(out_dir),
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(render_dir),
            text=True,
            capture_output=True,
            check=False,
            timeout=QUARTO_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            f"Quarto render timed out after {QUARTO_TIMEOUT_SECONDS}s for {template_name}. Generated fallback HTML artifact.",
        )
    except OSError as exc:
        return (
            False,
            f"Quarto execution error for {template_name}: {exc}. Generated fallback HTML artifact.",
        )

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if detail:
            return (
                False,
                f"Quarto render failed for {template_name}: {detail}. Generated fallback HTML artifact.",
            )
        return (
            False,
            f"Quarto render failed with non-zero exit code for {template_name}. Generated fallback HTML artifact.",
        )

    return True, None


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

        report_path = out_dir / REPORT_FILENAME
        quickview_path = out_dir / QUICKVIEW_FILENAME
        warnings: list[str] = []

        templates_dir = Path(__file__).resolve().parent / "templates"
        required_templates = {
            "report.qmd": report_path,
            "dashboard.qmd": quickview_path,
        }
        missing_templates = [
            name for name in required_templates if not (templates_dir / name).exists()
        ]
        if missing_templates:
            warning = (
                "Missing Quarto template(s): "
                + ", ".join(str(templates_dir / name) for name in missing_templates)
                + ". Generated fallback HTML artifacts."
            )
            warnings.append(warning)
            _write_fallback_html(
                report_path, warning, QUICKVIEW_FILENAME, "Open dashboard quickview"
            )
            _write_fallback_html(
                quickview_path,
                warning,
                REPORT_FILENAME,
                "Open deep-dive report",
            )
        else:
            quarto_bin = _find_quarto_bin()
            if not quarto_bin:
                warning = "Quarto binary 'quarto' not found in PATH. Generated fallback HTML artifacts."
                warnings.append(warning)
                _write_fallback_html(
                    report_path, warning, QUICKVIEW_FILENAME, "Open dashboard quickview"
                )
                _write_fallback_html(
                    quickview_path,
                    warning,
                    REPORT_FILENAME,
                    "Open deep-dive report",
                )
            else:
                tmp_dir, render_dir = _prepare_render_workspace(templates_dir, payload)
                try:
                    rendered_report, report_warning = _render_qmd(
                        quarto_bin=quarto_bin,
                        render_dir=render_dir,
                        out_dir=out_dir.resolve(),
                        template_name="report.qmd",
                        output_name=REPORT_FILENAME,
                    )
                    rendered_quickview, quickview_warning = _render_qmd(
                        quarto_bin=quarto_bin,
                        render_dir=render_dir,
                        out_dir=out_dir.resolve(),
                        template_name="dashboard.qmd",
                        output_name=QUICKVIEW_FILENAME,
                    )
                finally:
                    tmp_dir.cleanup()

                if report_warning:
                    warnings.append(report_warning)
                if quickview_warning:
                    warnings.append(quickview_warning)

                if not rendered_report:
                    _write_fallback_html(
                        report_path,
                        report_warning or "Failed to render report.qmd.",
                        QUICKVIEW_FILENAME,
                        "Open dashboard quickview",
                    )
                if not rendered_quickview:
                    _write_fallback_html(
                        quickview_path,
                        quickview_warning or "Failed to render dashboard.qmd.",
                        REPORT_FILENAME,
                        "Open deep-dive report",
                    )

        if not report_path.exists():
            warning = f"Expected report artifact was not created: {report_path}. Generated fallback HTML artifact."
            warnings.append(warning)
            _write_fallback_html(
                report_path, warning, QUICKVIEW_FILENAME, "Open dashboard quickview"
            )

        if not quickview_path.exists():
            warning = f"Expected quickview artifact was not created: {quickview_path}. Generated fallback HTML artifact."
            warnings.append(warning)
            _write_fallback_html(
                quickview_path, warning, REPORT_FILENAME, "Open deep-dive report"
            )

        return {
            "plugin": "quarto-portfolio-report",
            "artifacts": [
                {"type": "html", "path": str(report_path)},
                {"type": "html_dashboard", "path": str(quickview_path)},
                {"type": "json", "path": str(payload_path)},
                {"type": "js", "path": str(output_js_path)},
            ],
            "warnings": warnings,
        }
