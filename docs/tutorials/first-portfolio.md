# Tutorial: Your first portfolio

This tutorial walks you through validating, snapshotting, and visualizing
your first portfolio with rikdom. By the end you will have a `data/`
workspace, an HTML dashboard, and a baseline understanding of the canonical
files rikdom reads and writes.

If you want background instead of a guided lesson, see
[schema design](../explanation/schema-design.md). For specific tasks, see
the [how-to guides](../how-to/).

## What you will build

- A local workspace at `data/` with `portfolio.json` and `snapshots.jsonl`.
- A validated portfolio that passes schema and structural checks.
- One historical snapshot row with a base-currency total.
- An HTML dashboard at `out/dashboard.html`.

Estimated time: 5 minutes.

## Prerequisites

- macOS, Linux, or Windows shell.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed.

## 1. Sync dependencies

From the repo root:

```bash
make sync
```

This installs the project into a local virtualenv that `uv run` will use.

## 2. Bootstrap the workspace

The CLI auto-bootstraps `data/portfolio.json`, `data/snapshots.jsonl`, and
`data/fx_rates.jsonl` from the tracked `data-sample/` templates the first
time you run a default command. To seed them explicitly:

```bash
make bootstrap
```

After this you have:

```
data/
  portfolio.json     # current-state portfolio
  snapshots.jsonl    # append-only history (one JSON object per line)
  fx_rates.jsonl     # FX history used at snapshot time
```

The contents come from `data-sample/`. They are example data — safe to play
with. `data/` is gitignored.

## 3. Validate the portfolio

```bash
make validate
```

This runs schema validation, structural checks, and reconciliation. Expect
a clean run on the sample data. If you later edit `data/portfolio.json`,
re-run this to catch shape errors early.

## 4. Take a snapshot

```bash
make snapshot
```

Rikdom resolves FX, computes the aggregated base-currency total, and
**appends** a new row to `data/snapshots.jsonl` with a locked-in FX context
under `metadata.fx_lock`. The file is append-only — old history is never
rewritten.

Run `make snapshot` a second time and you'll see a second row.

## 5. Generate a dashboard

```bash
make viz
```

This produces `out/dashboard.html` and `out/portfolio-report.html`. Open
`out/dashboard.html` in a browser to see allocation, totals, and the
snapshot history you just appended.

## What you have learned

- Where rikdom keeps its state (`data/portfolio.json`, `data/snapshots.jsonl`).
- The `validate → snapshot → viz` flow that drives most workflows.
- That snapshots are append-only and FX-locked for reproducibility.

## Where to go next

- [Author your first plugin](first-plugin.md) — extend rikdom with your own importer.
- [Import a broker statement](../how-to/import-a-statement.md) — replace sample data with real data from a community plugin.
- [Compute portfolio TWR / MWR](../how-to/compute-performance.md) — measure returns over a window.
- [Schema design](../explanation/schema-design.md) — understand the data model behind `portfolio.json`.
