from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TEMPLATE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Rikdom Dashboard</title>
  <style>
    :root {
      --bg: #f5f4ef;
      --panel: #ffffff;
      --ink: #172026;
      --muted: #5f6a72;
      --accent: #1f7a8c;
      --accent-2: #f18f01;
      --line: #dbe1e6;
    }
    body {
      margin: 0;
      font-family: ui-rounded, system-ui, -apple-system, Segoe UI, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 20% -10%, #d9f0f5, var(--bg) 45%);
    }
    .wrap {
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }
    .title {
      font-size: 28px;
      margin: 0 0 8px;
    }
    .subtitle {
      color: var(--muted);
      margin: 0 0 20px;
    }
    .grid {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    }
    .half-grid {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 16px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 6px 20px rgba(12, 31, 47, 0.05);
    }
    .metric {
      font-size: 32px;
      font-weight: 650;
      margin: 8px 0;
      letter-spacing: 0.2px;
    }
    .muted { color: var(--muted); }
    svg { width: 100%; height: auto; border-radius: 8px; background: #f8fafb; }
    .dist {
      display: grid;
      gap: 14px;
      grid-template-columns: 190px 1fr;
      align-items: start;
    }
    .donut-wrap {
      display: grid;
      place-items: center;
    }
    .donut-center {
      font-size: 11px;
      fill: #4f5960;
      text-anchor: middle;
    }
    .legend {
      display: grid;
      gap: 6px;
      margin-top: 4px;
    }
    .legend-row {
      display: grid;
      grid-template-columns: 12px 1fr auto;
      gap: 8px;
      align-items: center;
      font-size: 13px;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
    }
    .value-col {
      text-align: right;
      color: #334047;
      font-variant-numeric: tabular-nums;
    }
    @media (max-width: 900px) {
      .half-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 680px) {
      .metric { font-size: 24px; }
      .dist { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1 class=\"title\">Rikdom</h1>
    <p class=\"subtitle\" id=\"subtitle\"></p>

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
          <div class=\"donut-wrap\"><svg id=\"asset-donut\" viewBox=\"0 0 180 180\"></svg></div>
          <div class=\"legend\" id=\"asset-legend\"></div>
        </div>
      </section>

      <section class=\"panel\">
        <div class=\"muted\" style=\"margin-bottom:10px;\">Market Value by Currency (converted to <span id=\"base-ccy\"></span>)</div>
        <div class=\"dist\">
          <div class=\"donut-wrap\"><svg id=\"currency-donut\" viewBox=\"0 0 180 180\"></svg></div>
          <div class=\"legend\" id=\"currency-legend\"></div>
        </div>
        <div class=\"muted\" id=\"currency-warning\" style=\"margin-top:8px;\"></div>
      </section>
    </div>
  </div>

  <script>
    const payload = __PAYLOAD__;
    const palette = ['#1f7a8c', '#f18f01', '#2f9e44', '#7b2cbf', '#d6336c', '#1c7ed6', '#ae3ec9', '#5c940d'];

    const fmt = (value, ccy) => new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: ccy,
      maximumFractionDigits: 2
    }).format(value);

    const fmtCompact = (value, ccy) => {
      const abs = Math.abs(value);
      let scaled = value;
      let suffix = '';
      if (abs >= 1_000_000_000) {
        scaled = value / 1_000_000_000;
        suffix = 'B';
      } else if (abs >= 1_000_000) {
        scaled = value / 1_000_000;
        suffix = 'M';
      } else if (abs >= 1_000) {
        scaled = value / 1_000;
        suffix = 'K';
      }
      const decimals = Math.abs(scaled) >= 100 ? 0 : 1;
      return `${new Intl.NumberFormat(undefined, {
        maximumFractionDigits: decimals,
        minimumFractionDigits: 0,
      }).format(scaled)}${suffix} ${ccy}`;
    };

    const pct = (value, total) => total > 0 ? `${((value / total) * 100).toFixed(1)}%` : '0.0%';

    const snapshots = payload.snapshots || [];
    const latest = snapshots[snapshots.length - 1];

    document.getElementById('subtitle').textContent = `${payload.profile} · base ${payload.base_currency}`;
    document.getElementById('base-ccy').textContent = payload.base_currency;
    if (latest) {
      document.getElementById('total').textContent = fmt(latest.totals.portfolio_value_base, payload.base_currency);
    }

    function renderLineChart(points) {
      const svg = document.getElementById('line');
      if (!points.length) {
        svg.innerHTML = '<text x="30" y="40" fill="#5f6a72">No snapshots yet</text>';
        return;
      }

      const values = points.map(p => Number(p?.totals?.portfolio_value_base) || 0);
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = Math.max(max - min, 1);

      const W = 700;
      const H = 240;
      const padLeft = 84;
      const padRight = 16;
      const padTop = 20;
      const padBottom = 40;
      const innerW = W - padLeft - padRight;
      const innerH = H - padTop - padBottom;

      const xFor = (i) => padLeft + (i / Math.max(points.length - 1, 1)) * innerW;
      const yFor = (v) => padTop + (1 - ((v - min) / range)) * innerH;
      const formatYm = (ts, idx) => (typeof ts === 'string' && ts.length >= 7 ? ts.slice(0, 7) : `#${idx + 1}`);

      const path = points.map((p, i) => {
        const x = xFor(i);
        const y = yFor(Number(p?.totals?.portfolio_value_base) || 0);
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      }).join(' ');

      const yTicks = 4;
      const yGrid = Array.from({ length: yTicks + 1 }).map((_, i) => {
        const ratio = i / yTicks;
        const v = max - ratio * (max - min);
        const y = yFor(v);
        return {
          y,
          label: fmtCompact(v, payload.base_currency),
        };
      });

      const xTickCount = Math.min(6, Math.max(points.length, 2));
      const xTickIndexes = [...new Set(Array.from({ length: xTickCount }).map((_, i) =>
        Math.round((i / Math.max(xTickCount - 1, 1)) * (points.length - 1))
      ))];

      svg.innerHTML = `
        ${yGrid.map(t => `<line x1="${padLeft}" y1="${t.y.toFixed(1)}" x2="${W - padRight}" y2="${t.y.toFixed(1)}" stroke="#eef2f5"/>`).join('')}
        <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${H - padBottom}" stroke="#c8d3db"/>
        <line x1="${padLeft}" y1="${H - padBottom}" x2="${W - padRight}" y2="${H - padBottom}" stroke="#c8d3db"/>
        <path d="${path}" fill="none" stroke="#1f7a8c" stroke-width="3" stroke-linecap="round"/>
        ${yGrid.map(t => `<text x="${padLeft - 8}" y="${(t.y + 4).toFixed(1)}" fill="#5f6a72" font-size="11" text-anchor="end">${t.label}</text>`).join('')}
        ${xTickIndexes.map((idx) => {
          const x = xFor(idx);
          const label = formatYm(points[idx]?.timestamp, idx);
          return `<text x="${x.toFixed(1)}" y="${H - 12}" fill="#5f6a72" font-size="11" text-anchor="middle">${label}</text>`;
        }).join('')}
      `;
    }

    function renderDistribution({ svgId, legendId, entries, total, formatValue, centerLabel }) {
      const svg = document.getElementById(svgId);
      const legend = document.getElementById(legendId);
      if (!entries.length || total <= 0) {
        svg.innerHTML = '<text x="90" y="95" class="donut-center">No data</text>';
        legend.innerHTML = '<div class="muted">No data</div>';
        return;
      }

      const cx = 90;
      const cy = 90;
      const r = 62;
      const strokeW = 22;
      const circumference = 2 * Math.PI * r;
      let offset = 0;

      const slices = entries.map((entry, index) => {
        const ratio = entry.value / total;
        const dash = Math.max(ratio * circumference, 0);
        const color = palette[index % palette.length];
        const piece = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="${strokeW}" stroke-linecap="butt" stroke-dasharray="${dash} ${circumference - dash}" stroke-dashoffset="-${offset}" transform="rotate(-90 ${cx} ${cy})"></circle>`;
        offset += dash;
        return { piece, color, ...entry };
      });

      svg.innerHTML = `
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#eef2f5" stroke-width="${strokeW}"></circle>
        ${slices.map(s => s.piece).join('')}
        <text x="${cx}" y="${cy - 6}" class="donut-center">${centerLabel}</text>
        <text x="${cx}" y="${cy + 12}" class="donut-center">${fmtCompact(total, payload.base_currency)}</text>
      `;

      legend.innerHTML = slices.map(slice => `
        <div class="legend-row">
          <span class="dot" style="background:${slice.color}"></span>
          <span>${slice.label} <span class="muted">(${pct(slice.value, total)})</span></span>
          <span class="value-col">${formatValue(slice)}</span>
        </div>
      `).join('');
    }

    function renderAssetClass(latestSnapshot) {
      const byClass = latestSnapshot?.totals?.by_asset_class || {};
      const entries = Object.entries(byClass)
        .map(([label, value]) => ({ label, value: Number(value) || 0 }))
        .filter(row => row.value > 0)
        .sort((a, b) => b.value - a.value);
      const total = entries.reduce((acc, row) => acc + row.value, 0);

      renderDistribution({
        svgId: 'asset-donut',
        legendId: 'asset-legend',
        entries,
        total,
        centerLabel: 'Asset class',
        formatValue: (row) => fmtCompact(row.value, payload.base_currency)
      });
    }

    function renderCurrencyConverted(currencyExposure) {
      const rows = Array.isArray(currencyExposure?.rows) ? currencyExposure.rows : [];
      const entries = rows
        .filter(row => typeof row.converted_base === 'number' && row.converted_base > 0)
        .map(row => ({
          label: row.currency,
          value: row.converted_base,
          native_amount: row.native_amount
        }))
        .sort((a, b) => b.value - a.value);

      const total = entries.reduce((acc, row) => acc + row.value, 0);

      renderDistribution({
        svgId: 'currency-donut',
        legendId: 'currency-legend',
        entries,
        total,
        centerLabel: 'Currency FX',
        formatValue: (row) => `${fmtCompact(row.value, payload.base_currency)} · ${fmtCompact(row.native_amount, row.label)}`
      });

      const missing = Array.isArray(currencyExposure?.missing_rates) ? currencyExposure.missing_rates : [];
      const warning = document.getElementById('currency-warning');
      if (missing.length) {
        warning.textContent = `Missing FX rates for: ${missing.join(', ')}`;
      } else {
        warning.textContent = '';
      }
    }

    renderLineChart(snapshots);
    renderAssetClass(latest);
    renderCurrencyConverted(payload.currency_exposure || {});
  </script>
</body>
</html>
"""


def write_dashboard(
    profile_name: str,
    base_currency: str,
    snapshots: list[dict[str, Any]],
    out_path: str | Path,
    *,
    currency_exposure: dict[str, Any] | None = None,
) -> Path:
    payload = {
        "profile": profile_name,
        "base_currency": base_currency,
        "snapshots": snapshots,
        "currency_exposure": currency_exposure or {},
    }

    html = TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
