# Dashboard UI kit

A high-fidelity recreation of the **static dashboard** that `rikdom dashboard` generates into `site/`. Zero-dependency, print-friendly, a handbook for your wealth.

## Files

- `index.html` — the dashboard view with summary, allocation, holdings table, operations, and snapshot history.
- `Header.jsx` — brand + metadata strip.
- `Summary.jsx` — the top-of-page figures (value, delta, asset count).
- `Allocation.jsx` — stacked allocation bar + legend.
- `HoldingsTable.jsx` — the main holdings list, grouped by class.
- `Operations.jsx` — recurring operations with last-done / next-due.
- `SnapshotChart.jsx` — 12-month line chart drawn in inline SVG.
