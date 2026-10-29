# Render a portfolio report

Use this guide to produce HTML dashboards and reports from your local
portfolio. Visualization in rikdom is plugin-driven through the
`output` hook (e.g. `quarto-portfolio-report`).

## Quick render

```bash
make viz
```

Produces:

- `out/dashboard.html` — quickview.
- `out/portfolio-report.html` — deep dive.

Both pages link to each other. Open `out/dashboard.html` in a browser.

## Include the current state

To add a synthetic snapshot for "right now" in addition to the recorded
history:

```bash
uv run rikdom viz --data-dir data --out-root out --include-current
```

## Use a different output plugin

```bash
uv run rikdom viz \
  --plugin quarto-portfolio-report \
  --plugins-dir plugins \
  --data-dir data --out-root out
```

Any plugin declaring the `output` hook can be selected with `--plugin`.
List available plugins:

```bash
uv run rikdom plugins list --plugins-dir plugins
```

## Inputs

- Portfolio profile and base currency from `data/portfolio.json`.
- Time series from `data/snapshots.jsonl`.
- Optional current-state synthetic snapshot via `--include-current`.

## Keep the report usable offline

Keep the whole output directory together, including `report-data.js` and any
Quarto-generated `*_files/` folders. Open `dashboard.html` directly in a browser;
no server or live provider is needed. Missing Quarto or a render failure produces
a clearly labelled fallback page with valuation, quality context, and local trust
links; the fallback omits charts and the detailed holdings table.

The deep-dive holdings table scrolls horizontally on small screens. Keyboard
users can Tab to the table and use arrow keys to reach every column. Both pages
link back to each other.

See [offline desktop/mobile browser QA](report-browser-qa.md) for reproducible
checks, optional browser tests, and the current English/Portuguese limitations.

## See also

- [Received-income JSON/Markdown reports](summarize-income.md) — separate artifacts generated with `rikdom income`.
- [CLI reference: visualization](../reference/cli.md#visualization)
- [Plugin architecture](../explanation/plugin-architecture.md)

## Inspect data quality

Both views and the fallback HTML show current valuation separately from historical
snapshot totals, quantity-comparison coverage, warnings, and excluded holdings.
Current converted values come from core trust records. The output also includes
`holding_trust.json`, `holding_trust.md`, `reconciliation.json`, and
`reconciliation.md`, linked locally from the report. Missing source history never
becomes a successful comparison merely because no mismatch was found.

Rendering uses supplied snapshot FX locks and holding metadata fallback without
network acquisition. Inspect the recorded effective dates; an old or undated rate
is not made current by generating a new report.


## Include offline investment performance

The Quarto plugin and fallback HTML display the same performance contract as
`rikdom performance`, with the actual snapshot window, return method,
annualization, fees/taxes convention, growth bridge and warnings. Select local
flow-valuation, historical FX, policy and benchmark inputs through
`extensions.rikdom_report.performance`; see the
[plugin's performance preferences](../../plugins/quarto-portfolio-report/README.md#offline-investment-performance).
Use the same files and window as the CLI to reproduce its figures. Interactive
date or dimension filters make unsupported performance unavailable until reset;
they do not relabel the full-portfolio calculation as a filtered return.


## Show profit and historical valuation evidence

Pass `--historical-fx`, `--flow-valuations`, `--historical-valuations`,
`--profit-basis`, `--policy`, `--benchmarks-dir`, `--since`, and `--until` to
`viz` as needed. The full and fallback pages display the same core return and
profit contracts as the CLI. See [reproduce historical valuations and profit](replay-performance-data.md)
for working local examples and supported scope/date behavior.
