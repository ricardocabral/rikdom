# Dashboard UI kit

A design prototype for a **static dashboard**: print-friendly, a handbook for your wealth. Its illustrative `rikdom dashboard` command and `site/` output are not implemented CLI behavior. The current `rikdom viz` command renders `out/dashboard.html` and `out/portfolio-report.html` through an output plugin; see the [report guide](../../../../docs/how-to/render-a-report.md).

## Files

- `index.html` — the dashboard view with summary, allocation, holdings table, operations, and snapshot history.
- `Header.jsx` — brand + metadata strip.
- `Summary.jsx` — the top-of-page figures (value, delta, asset count).
- `Allocation.jsx` — stacked allocation bar + legend.
- `HoldingsTable.jsx` — the main holdings list, grouped by class.
- `Operations.jsx` — recurring operations with last-done / next-due.
- `SnapshotChart.jsx` — 12-month line chart drawn in inline SVG.
