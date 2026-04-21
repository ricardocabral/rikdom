# Native Multi-Currency Engine (User Guide)

This guide explains the default multi-currency workflow in rikdom and how snapshot-time FX valuation works.

## How snapshot valuation works

When you run `rikdom snapshot`, rikdom performs this flow:

1. Inspect all holding currencies in the portfolio.
2. For each non-base currency, read the best available historical rate from `fx_rates.jsonl` for the snapshot date.
3. If a rate is missing, auto-fetch it and append it to `fx_rates.jsonl`.
4. Aggregate holdings using the resolved FX rates.
5. Persist the snapshot with `metadata.fx_lock` containing:
   - `rates_to_base`
   - `rate_dates`
   - `sources`

This makes snapshot valuation deterministic and auditable over time.

## Commands

Use the default FX history file (`data/fx_rates.jsonl`):

```bash
uv run rikdom snapshot --portfolio data/portfolio.json --snapshots data/snapshots.jsonl
```

Disable automatic FX ingestion (history lookup only):

```bash
uv run rikdom snapshot --no-fx-auto-ingest
```

Use a custom FX history file:

```bash
uv run rikdom snapshot --fx-history data/custom_fx_rates.jsonl
```

## Compatibility fallback

If a holding still has `metadata.fx_rate_to_base`, rikdom can use it as a compatibility fallback and emits a warning so you can migrate progressively to history-driven FX.
