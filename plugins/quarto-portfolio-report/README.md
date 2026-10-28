# quarto-portfolio-report

Pluggy `output` plugin that renders a portfolio report with Quarto.

## Prerequisites

Install Quarto CLI and ensure it is available in `PATH`:

```bash
brew install --cask quarto
quarto --version
```

If Quarto is missing, the plugin still runs but generates a fallback HTML artifact.

## Run

Quick target from repo root:

```bash
make viz
```

Full command:

```bash
uv run rikdom viz \
  --portfolio data-sample/portfolio.json \
  --snapshots data-sample/snapshots.jsonl \
  --out out/reports/dashboard.html
```


## Current values and trust artifacts

The output plugin builds one core aggregation result for the current holdings.
Its total, base-currency holding amounts, allocations, and excluded holdings all
use that result. Historical snapshot totals remain a separate timeline; they do
not replace the current valuation.

The current valuation uses the latest supplied compatible snapshot FX lock,
then the existing per-holding metadata fallback. It never acquires rates or
contacts a provider. Available lock effective dates and sources appear in trust
context; unknown or older rate dates stay visible as warnings. Report generation
time is separate from the rate's effective date.

Both views and fallback HTML include a small data-quality section with coverage,
quantity comparison counts, exclusions, warnings, and local links to:

- `holding_trust.json` and `holding_trust.md`
- `reconciliation.json` and `reconciliation.md`

These artifacts use the same report builder and writer as `rikdom reconcile`.
Zero findings do not establish complete history. Coverage describes only the
explicitly declared source scopes and periods.
