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

## See also

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
