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
uv run rikdom visualize --data-dir data --out-root out --include-current
```

## Use a different output plugin

```bash
uv run rikdom render-report \
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
