# Tutorial: Your first portfolio

Import a sample statement, inspect income and trust evidence, and create a local
snapshot and HTML report. Estimated time: 10–15 minutes after installation. This
is a walkthrough estimate, not a measured usability result.

## Prerequisites and installation

Use a macOS or Linux shell (or WSL on Windows), with `make` and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed. Run
all commands from the repository root.

```bash
make sync
```

Installation downloads dependencies and requires network access. The remaining
steps use tracked samples and local files; no account, paid API, or AI service is
needed. `uv run --offline --no-sync` uses the environment you just installed.

## 1. Create a sample workspace

Use a separate directory for this lesson:

```bash
make bootstrap DATA_DIR=data/tutorial OUT_DIR=out/tutorial
```

This copies `portfolio.json`, `snapshots.jsonl`, `policy.json`, local
`fx_rates.jsonl`, and benchmark samples from `data-sample/`. Repeating bootstrap
preserves existing files. Expected numbers below assume a fresh directory.
`data/` and `out/` are gitignored, including these lesson directories.

## 2. Preview the statement

```bash
uv run --offline --no-sync rikdom import-statement \
  --data-dir data/tutorial --out-root out/tutorial \
  --plugin csv-generic --input data-sample/sample_statement.csv --dry-run
```

In `dry_run_diff.summary`, expect two holdings and three activities with
`create` counts of 2 and 3. `write` is `false`. The portfolio, history, import log,
and report artifacts are unchanged. Inspect `import_diagnostics`: this source
reports **unknown** history coverage.

## 3. Apply and repeat the import

```bash
uv run --offline --no-sync rikdom import-statement \
  --data-dir data/tutorial --out-root out/tutorial \
  --plugin csv-generic --input data-sample/sample_statement.csv --write --reconcile
```

Expect `holdings.inserted: 2` and `activities.inserted: 3`. Run the same command
again. Expect zero inserts and updates, with two holdings and three activities
skipped. The holdings and events are deduplicated; each written run still appends
an audit entry to `data/tutorial/import_log.jsonl`.

Open `out/tutorial/reports/holding_trust.md` and
`out/tutorial/reports/reconciliation.md`. The valuation invariant matches, but
history remains unknown and quantity reconciliation is not computable for four
holdings. Zero findings do not establish complete transaction history.

## 4. Validate the result

```bash
uv run --offline --no-sync rikdom validate \
  --data-dir data/tutorial --out-root out/tutorial
```

The sample passes validation. Inspect warnings and trust evidence before relying
on totals. Re-run validation after editing the portfolio.

## 5. Append a snapshot using local FX

Use a fixed sample date so the lesson is reproducible:

```bash
uv run --offline --no-sync rikdom snapshot \
  --data-dir data/tutorial --out-root out/tutorial \
  --timestamp 2026-04-21T10:00:00Z --no-fx-auto-ingest
```

This appends one row to `data/tutorial/snapshots.jsonl`, preserving previous
rows. Its `metadata.fx_lock.rates_to_base.USD` is `5.25`, from the tracked local
FX history. These are example historical rates, not current market prices.

## 6. Read received income

```bash
uv run --offline --no-sync rikdom income \
  --data-dir data/tutorial --out-root out/tutorial \
  --start 2026-01-01 --end 2026-12-31
```

Open `out/tutorial/reports/income.md` and `income.json`. Expect:

| Period | Currency | Gross income |
| --- | --- | ---: |
| February 2026 | USD | 1.20 |
| March 2026 | BRL | 45.70 |
| April 2026 | BRL | 96.00 |

Yearly totals stay separate: **BRL 141.70** and **USD 1.20**. The April dividend
was already in the seed portfolio. The imported BRL 12.50 reimbursement is
excluded from income. Net receipts and withholding are unavailable for all three
income events because the sources do not assert withholding, including whether
it was zero. Read the three diagnostics; do not interpret unknown amounts as zero.
Income reporting leaves holdings and snapshots unchanged.

## 7. Generate the offline fallback report

```bash
RIKDOM_DISABLE_QUARTO=1 uv run --offline --no-sync rikdom viz \
  --data-dir data/tutorial --out-root out/tutorial
```

Open `out/tutorial/dashboard.html` and `out/tutorial/portfolio-report.html` in a
browser. Both show **Fallback Portfolio Report**, valuation, history and data
quality evidence. This path works without Quarto and does not provide the full
interactive charts. To render the full dashboard after separately installing
Quarto, run the command without `RIKDOM_DISABLE_QUARTO=1`; that rendering path is
outside this offline lesson.

You have previewed, applied, and replayed an import, checked trust and income,
and saved an FX-locked snapshot and local report.

## Next steps

- [Import a broker statement](../how-to/import-a-statement.md) — choose an importer for your own files.
- [Summarize received dividends and interest](../how-to/summarize-income.md) — inspect other periods and source conventions.
- [Compute portfolio TWR / MWR](../how-to/compute-performance.md) — measure returns over a window.
- [Schema design](../explanation/schema-design.md) — understand the canonical files.
