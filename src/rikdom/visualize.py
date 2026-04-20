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
      max-width: 1000px;
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
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
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
    .bars { display: grid; gap: 8px; }
    .bar-row { display: grid; grid-template-columns: 130px 1fr auto; align-items: center; gap: 8px; font-size: 14px; }
    .bar-track { height: 9px; background: #edf2f5; border-radius: 999px; overflow: hidden; }
    .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }
    svg { width: 100%; height: auto; border-radius: 8px; background: #f8fafb; }
    @media (max-width: 680px) {
      .metric { font-size: 24px; }
      .bar-row { grid-template-columns: 92px 1fr auto; font-size: 12px; }
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

    <section class=\"panel\" style=\"margin-top: 16px;\">
      <div class=\"muted\" style=\"margin-bottom:10px;\">Current Allocation by Asset Class</div>
      <div class=\"bars\" id=\"bars\"></div>
    </section>
  </div>

  <script>
    const payload = __PAYLOAD__;

    const fmt = (value, ccy) => new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: ccy,
      maximumFractionDigits: 2
    }).format(value);

    const snapshots = payload.snapshots || [];
    const latest = snapshots[snapshots.length - 1];

    document.getElementById('subtitle').textContent = `${payload.profile} · base ${payload.base_currency}`;
    if (latest) {
      document.getElementById('total').textContent = fmt(latest.totals.portfolio_value_base, payload.base_currency);
    }

    function renderLineChart(points) {
      const svg = document.getElementById('line');
      if (!points.length) {
        svg.innerHTML = '<text x="30" y="40" fill="#5f6a72">No snapshots yet</text>';
        return;
      }

      const values = points.map(p => p.totals.portfolio_value_base);
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = Math.max(max - min, 1);

      const W = 700;
      const H = 240;
      const padX = 24;
      const padY = 24;
      const innerW = W - padX * 2;
      const innerH = H - padY * 2;

      const path = points.map((p, i) => {
        const x = padX + (i / Math.max(points.length - 1, 1)) * innerW;
        const y = padY + (1 - ((p.totals.portfolio_value_base - min) / range)) * innerH;
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      }).join(' ');

      svg.innerHTML = `
        <line x1="${padX}" y1="${H - padY}" x2="${W-padX}" y2="${H-padY}" stroke="#c8d3db"/>
        <path d="${path}" fill="none" stroke="#1f7a8c" stroke-width="3" stroke-linecap="round"/>
        <text x="${padX}" y="18" fill="#5f6a72" font-size="12">${fmt(max, payload.base_currency)}</text>
        <text x="${padX}" y="${H - 8}" fill="#5f6a72" font-size="12">${fmt(min, payload.base_currency)}</text>
      `;
    }

    function renderBars(latestSnapshot) {
      const bars = document.getElementById('bars');
      if (!latestSnapshot) {
        bars.innerHTML = '<div class="muted">No data</div>';
        return;
      }

      const byClass = latestSnapshot.totals.by_asset_class || {};
      const total = Object.values(byClass).reduce((a, b) => a + b, 0);
      const entries = Object.entries(byClass).sort((a, b) => b[1] - a[1]);

      bars.innerHTML = entries.map(([label, value]) => {
        const ratio = total > 0 ? (value / total) * 100 : 0;
        return `
          <div class="bar-row">
            <div>${label}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${ratio.toFixed(1)}%"></div></div>
            <div>${ratio.toFixed(1)}%</div>
          </div>
        `;
      }).join('');
    }

    renderLineChart(snapshots);
    renderBars(latest);
  </script>
</body>
</html>
"""


def write_dashboard(
    profile_name: str,
    base_currency: str,
    snapshots: list[dict[str, Any]],
    out_path: str | Path,
) -> Path:
    payload = {
        "profile": profile_name,
        "base_currency": base_currency,
        "snapshots": snapshots,
    }

    html = TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
