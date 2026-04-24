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
QUICKVIEW_FILENAME = "dashboard.html"


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
        currency_raw = str(market_value.get("currency", "")).strip().upper()
        if amount is None or not currency_raw:
            continue
        currency = (
            currency_raw if len(currency_raw) == 3 and currency_raw.isalpha() else "UNKNOWN"
        )

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
        currency_raw = str(market_value.get("currency", "")).upper().strip()
        currency = (
            currency_raw if len(currency_raw) == 3 and currency_raw.isalpha() else "UNKNOWN"
        )
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

    top_holdings: list[dict[str, Any]] = []
    for holding in normalized_holdings:
        market_value = holding.get("market_value", {})
        amount = 0.0
        currency = base_currency
        if isinstance(market_value, dict):
            parsed_amount = _safe_float(market_value.get("amount"))
            if parsed_amount is not None:
                amount = parsed_amount
            currency = (
                str(market_value.get("currency", currency)).upper().strip() or currency
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

    fx_rates_to_base = _latest_fx_rates_to_base(snapshots, base_currency=base_currency)
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


def _write_fallback_html(path: Path, reason: str) -> None:
    path.write_text(
        (
            "<html><body>"
            "<h1>Fallback Portfolio Report</h1>"
            f"<p>{escape(reason)}</p>"
            f'<p><a href="{QUICKVIEW_FILENAME}">Open dashboard quickview</a></p>'
            "</body></html>"
        ),
        encoding="utf-8",
    )


def _write_quickview_html(path: Path) -> None:
    path.write_text(
        """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Rikdom Quickview</title>
  <style>
    :root { --bg:#f5f4ef; --panel:#fff; --ink:#172026; --muted:#5f6a72; --line:#dbe1e6; --accent:#1f7a8c; }
    body { margin:0; font-family:ui-rounded,system-ui,-apple-system,Segoe UI,sans-serif; color:var(--ink); background:radial-gradient(circle at 20% -10%, #d9f0f5, var(--bg) 45%); }
    .wrap { max-width:1100px; margin:0 auto; padding:24px; }
    .head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
    .title { font-size:28px; margin:0 0 6px; }
    .subtitle { color:var(--muted); margin:0 0 18px; }
    .link { color:#fff; background:var(--accent); text-decoration:none; padding:8px 12px; border-radius:10px; font-size:14px; }
    .grid { display:grid; gap:16px; grid-template-columns:repeat(auto-fit, minmax(320px,1fr)); }
    .half-grid { display:grid; gap:16px; grid-template-columns:repeat(2,minmax(0,1fr)); margin-top:16px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:16px; box-shadow:0 6px 20px rgba(12,31,47,.05); }
    .metric { font-size:32px; font-weight:650; margin:8px 0; }
    .muted { color:var(--muted); }
    svg { width:100%; height:auto; border-radius:8px; background:#f8fafb; }
    .dist { display:grid; gap:14px; grid-template-columns:190px 1fr; align-items:start; }
    .legend { display:grid; gap:6px; margin-top:4px; }
    .legend-row { display:grid; grid-template-columns:12px 1fr auto; gap:8px; align-items:center; font-size:13px; }
    .dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
    .value-col { text-align:right; color:#334047; font-variant-numeric:tabular-nums; }
    .donut-center { font-size:11px; fill:#4f5960; text-anchor:middle; }
    @media (max-width:900px) { .half-grid{grid-template-columns:1fr;} }
    @media (max-width:680px) { .metric{font-size:24px;} .dist{grid-template-columns:1fr;} }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"head\">
      <div>
        <h1 class=\"title\">Rikdom Quickview</h1>
        <p class=\"subtitle\" id=\"subtitle\"></p>
      </div>
      <a class=\"link\" href=\"portfolio-report.html\">Open deep-dive report</a>
    </div>

    <div class=\"grid\">
      <section class=\"panel\">
        <div class=\"muted\">Current Total</div>
        <div class=\"metric\" id=\"total\">-</div>
        <div class=\"muted\">Based on latest snapshot</div>
      </section>
      <section class=\"panel\">
        <div class=\"muted\">Progress Over Time</div>
        <svg id=\"line\" viewBox=\"0 0 700 240\" preserveAspectRatio=\"none\"></svg>
      </section>
    </div>

    <div class=\"half-grid\">
      <section class=\"panel\">
        <div class=\"muted\" style=\"margin-bottom:10px;\">Current Allocation by Asset Class</div>
        <div class=\"dist\">
          <svg id=\"asset-donut\" viewBox=\"0 0 180 180\"></svg>
          <div class=\"legend\" id=\"asset-legend\"></div>
        </div>
      </section>

      <section class=\"panel\">
        <div class=\"muted\" style=\"margin-bottom:10px;\">Market Value by Currency (converted to <span id=\"base-ccy\"></span>)</div>
        <div class=\"dist\">
          <svg id=\"currency-donut\" viewBox=\"0 0 180 180\"></svg>
          <div class=\"legend\" id=\"currency-legend\"></div>
        </div>
        <div class=\"muted\" id=\"currency-warning\" style=\"margin-top:8px;\"></div>
      </section>
    </div>
  </div>

  <script src=\"report-data.js\"></script>
  <script>
    (() => {
      const payload = window.RIKDOM_REPORT_DATA || {};
      const sections = payload.sections || {};
      const quick = sections.quickview || {};
      const palette = ['#1f7a8c','#f18f01','#2f9e44','#7b2cbf','#d6336c','#1c7ed6','#ae3ec9','#5c940d'];

      const baseCurrency = String(payload?.profile?.base_currency || 'USD').toUpperCase();
      const profileName = String(payload?.profile?.display_name || 'Portfolio');
      const snapshots = Array.isArray(sections.timeline) ? sections.timeline : [];
      const latest = snapshots.length ? snapshots[snapshots.length - 1] : null;

      const CCY_RE = /^[A-Z]{3}$/;
      const safeCcy = (ccy) => {
        const s = String(ccy == null ? '' : ccy).toUpperCase();
        return CCY_RE.test(s) ? s : '';
      };
      const escapeHtml = (value) => String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
      const fmt = (value, ccy) => {
        const code = safeCcy(ccy);
        if (!code) return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(value) || 0);
        return new Intl.NumberFormat(undefined, { style:'currency', currency: code, maximumFractionDigits: 2 }).format(Number(value) || 0);
      };
      const fmtCompact = (value, ccy) => {
        const code = safeCcy(ccy);
        const num = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value) || 0);
        return code ? `${num} ${code}` : num;
      };
      const pct = (value, total) => total > 0 ? `${((value / total) * 100).toFixed(1)}%` : '0.0%';

      document.getElementById('subtitle').textContent = `${profileName} · base ${baseCurrency}`;
      document.getElementById('base-ccy').textContent = baseCurrency;
      if (latest && typeof latest.portfolio_value_base === 'number') {
        document.getElementById('total').textContent = fmt(latest.portfolio_value_base, baseCurrency);
      }

      function renderLineChart(points) {
        const svg = document.getElementById('line');
        if (!points.length) {
          svg.innerHTML = '<text x="30" y="40" fill="#5f6a72">No snapshots yet</text>';
          return;
        }
        const values = points.map(p => Number(p?.portfolio_value_base) || 0);
        const min = Math.min(...values); const max = Math.max(...values); const range = Math.max(max - min, 1);
        const W=700,H=240,padLeft=84,padRight=16,padTop=20,padBottom=40,innerW=W-padLeft-padRight,innerH=H-padTop-padBottom;
        const xFor = (i) => padLeft + (i / Math.max(points.length - 1, 1)) * innerW;
        const yFor = (v) => padTop + (1 - ((v - min) / range)) * innerH;
        const formatYm = (ts, idx) => (typeof ts === 'string' && ts.length >= 7 ? ts.slice(0, 7) : `#${idx + 1}`);
        const path = points.map((p, i) => `${i===0?'M':'L'} ${xFor(i).toFixed(1)} ${yFor(Number(p?.portfolio_value_base)||0).toFixed(1)}`).join(' ');
        const yTicks = 4;
        const yGrid = Array.from({ length: yTicks + 1 }).map((_, i) => {
          const ratio = i / yTicks; const v = max - ratio * (max - min); const y = yFor(v);
          return { y, label: fmtCompact(v, baseCurrency) };
        });
        const xTickCount = Math.min(6, Math.max(points.length, 2));
        const xTickIndexes = [...new Set(Array.from({ length: xTickCount }).map((_, i) => Math.round((i / Math.max(xTickCount - 1, 1)) * (points.length - 1))))];

        svg.innerHTML = `
          ${yGrid.map(t => `<line x1=\"${padLeft}\" y1=\"${t.y.toFixed(1)}\" x2=\"${W - padRight}\" y2=\"${t.y.toFixed(1)}\" stroke=\"#eef2f5\"/>`).join('')}
          <line x1=\"${padLeft}\" y1=\"${padTop}\" x2=\"${padLeft}\" y2=\"${H - padBottom}\" stroke=\"#c8d3db\"/>
          <line x1=\"${padLeft}\" y1=\"${H - padBottom}\" x2=\"${W - padRight}\" y2=\"${H - padBottom}\" stroke=\"#c8d3db\"/>
          <path d=\"${path}\" fill=\"none\" stroke=\"#1f7a8c\" stroke-width=\"3\" stroke-linecap=\"round\"/>
          ${yGrid.map(t => `<text x=\"${padLeft - 8}\" y=\"${(t.y + 4).toFixed(1)}\" fill=\"#5f6a72\" font-size=\"11\" text-anchor=\"end\">${escapeHtml(t.label)}</text>`).join('')}
          ${xTickIndexes.map((idx) => `<text x=\"${xFor(idx).toFixed(1)}\" y=\"${H - 12}\" fill=\"#5f6a72\" font-size=\"11\" text-anchor=\"middle\">${escapeHtml(formatYm(points[idx]?.timestamp, idx))}</text>`).join('')}
        `;
      }

      function renderDistribution({ svgId, legendId, entries, total, formatValue, centerLabel }) {
        const svg = document.getElementById(svgId); const legend = document.getElementById(legendId);
        if (!entries.length || total <= 0) {
          svg.innerHTML = '<text x="90" y="95" class="donut-center">No data</text>';
          legend.innerHTML = '<div class="muted">No data</div>';
          return;
        }
        const cx=90, cy=90, r=62, strokeW=22, circumference=2*Math.PI*r; let offset=0;
        const slices = entries.map((entry, index) => {
          const ratio = entry.value / total; const dash = Math.max(ratio * circumference, 0); const color = palette[index % palette.length];
          const piece = `<circle cx=\"${cx}\" cy=\"${cy}\" r=\"${r}\" fill=\"none\" stroke=\"${color}\" stroke-width=\"${strokeW}\" stroke-dasharray=\"${dash} ${circumference - dash}\" stroke-dashoffset=\"-${offset}\" transform=\"rotate(-90 ${cx} ${cy})\"></circle>`;
          offset += dash;
          return { piece, color, ...entry };
        });
        svg.innerHTML = `
          <circle cx=\"${cx}\" cy=\"${cy}\" r=\"${r}\" fill=\"none\" stroke=\"#eef2f5\" stroke-width=\"${strokeW}\"></circle>
          ${slices.map(s => s.piece).join('')}
          <text x=\"${cx}\" y=\"${cy - 6}\" class=\"donut-center\">${escapeHtml(centerLabel)}</text>
          <text x=\"${cx}\" y=\"${cy + 12}\" class=\"donut-center\">${escapeHtml(fmtCompact(total, baseCurrency))}</text>
        `;
        legend.innerHTML = slices.map(slice => `
          <div class=\"legend-row\">
            <span class=\"dot\" style=\"background:${escapeHtml(slice.color)}\"></span>
            <span>${escapeHtml(slice.label)} <span class=\"muted\">(${escapeHtml(pct(slice.value, total))})</span></span>
            <span class=\"value-col\">${escapeHtml(formatValue(slice))}</span>
          </div>
        `).join('');
      }

      const assetClass = Object.entries(latest?.by_asset_class || quick.latest_by_asset_class || {})
        .map(([label, value]) => ({ label, value: Number(value) || 0 }))
        .filter(row => row.value > 0)
        .sort((a, b) => b.value - a.value);
      renderDistribution({
        svgId: 'asset-donut',
        legendId: 'asset-legend',
        entries: assetClass,
        total: assetClass.reduce((a, b) => a + b.value, 0),
        centerLabel: 'Asset class',
        formatValue: (row) => fmtCompact(row.value, baseCurrency)
      });

      const native = quick?.currency?.native || {};
      const converted = quick?.currency?.converted_base || {};
      const currencyEntries = Object.entries(converted)
        .map(([currency, value]) => ({ label: currency, value: Number(value) || 0, native: Number(native[currency] || 0) }))
        .filter(row => row.value > 0)
        .sort((a, b) => b.value - a.value);
      renderDistribution({
        svgId: 'currency-donut',
        legendId: 'currency-legend',
        entries: currencyEntries,
        total: currencyEntries.reduce((a, b) => a + b.value, 0),
        centerLabel: 'Currency FX',
        formatValue: (row) => `${fmtCompact(row.value, baseCurrency)} · ${fmtCompact(row.native, row.label)}`
      });

      const missing = Array.isArray(quick?.currency?.missing_rates) ? quick.currency.missing_rates : [];
      document.getElementById('currency-warning').textContent = missing.length ? `Missing FX rates for: ${missing.join(', ')}` : '';

      renderLineChart(snapshots);
    })();
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )


def _render_with_quarto(template_dir: Path, out_dir: Path) -> tuple[bool, str | None]:
    quarto_bin = _find_quarto_bin()
    if not quarto_bin:
        return (
            False,
            "Quarto binary 'quarto' not found in PATH. Generated fallback HTML artifact.",
        )

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
        return (
            False,
            f"Quarto execution error: {exc}. Generated fallback HTML artifact.",
        )

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if detail:
            return (
                False,
                f"Quarto render failed: {detail}. Generated fallback HTML artifact.",
            )
        return (
            False,
            "Quarto render failed with non-zero exit code. Generated fallback HTML artifact.",
        )

    return True, None


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

        quickview_path = out_dir / QUICKVIEW_FILENAME
        _write_quickview_html(quickview_path)

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
                {"type": "html_dashboard", "path": str(quickview_path)},
                {"type": "json", "path": str(payload_path)},
                {"type": "js", "path": str(output_js_path)},
            ],
            "warnings": warnings,
        }
