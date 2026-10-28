# Tutorial: Your first portfolio

This tutorial walks you through validating, snapshotting, visualizing, and
summarizing income for your first portfolio with rikdom. By the end you will have a `data/`
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
- A received-income report at `out/reports/income.md`.

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

Seed the workspace from the tracked `data-sample/` templates before running
the commands below. The `income` command requires existing input and does not
create sample data automatically:

```bash
make bootstrap
cp -n data-sample/fx_rates.jsonl data/fx_rates.jsonl
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

This runs schema validation, structural checks, and reconciliation. The sample
passes validation; warnings can identify missing line-item FX references or
incomplete history. Inspect them before relying on a total. If you later edit
`data/portfolio.json`, re-run this to catch shape errors early.

## 4. Take a snapshot

```bash
make snapshot
```

Using local FX history, Rikdom computes the aggregated base-currency total, and
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

## 6. Inspect the evidence

```bash
uv run rikdom reconcile --data-dir data --out-root out
```

Open `out/reports/holding_trust.md` to see source amounts, FX and exclusions,
and `out/reports/reconciliation.md` for findings. Unknown history is not a clean
quantity reconciliation. No account, paid API, or AI service is needed.

## 7. Inspect received income

```bash
uv run rikdom income --data-dir data --out-root out \
  --start 2026-01-01 --end 2026-12-31
```

Open `out/reports/income.md`. The unchanged sample has one April 2026 dividend:
BRL 96 of gross income. Net receipts are unavailable because the source does not
assert withholding, including whether it was zero. Inspect the diagnostic and
compare it with the event row in `out/reports/income.json`.

This report reads the activity ledger without changing holdings or snapshots.
For other imports and date ranges, use the [income guide](../how-to/summarize-income.md).

## What you have learned

- Where rikdom keeps its state (`data/portfolio.json`, `data/snapshots.jsonl`).
- The `validate → snapshot → viz` flow that drives most workflows.
- That snapshots are append-only and FX-locked for reproducibility.
- How to inspect received income and recognize an unavailable net amount.

## Where to go next

- [Author your first plugin](first-plugin.md) — extend rikdom with your own importer.
- [Import a broker statement](../how-to/import-a-statement.md) — replace sample data with real data from a community plugin.
- [Summarize received dividends and interest](../how-to/summarize-income.md) — inspect other periods and source conventions.
- [Compute portfolio TWR / MWR](../how-to/compute-performance.md) — measure returns over a window.
- [Schema design](../explanation/schema-design.md) — understand the data model behind `portfolio.json`.
