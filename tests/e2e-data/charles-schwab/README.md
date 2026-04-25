# Charles Schwab E2E data folder

This folder contains a clean workspace for end-to-end import tests with the `charles-schwab` plugin.

## Files

- `portfolio.json`: clean canonical portfolio for repeatable imports
- `snapshots.jsonl`: optional snapshot ledger (empty by default)
- `fx_rates.jsonl`: FX history used by the multi-currency E2E assertion
- `import_log.jsonl`: optional import log (empty by default)
- `input-taxable-mixed.csv`: taxable account fixture with USD and EUR accounts
- `input-ira-income.csv`: IRA fixture
- `input-invalid-fees.csv`: negative fixture for malformed transaction fees
- `input-invalid-buy-quantity.csv`: negative fixture for missing buy/sell quantity

## Run E2E import

```bash
PYTHONPATH=src uv run rikdom import-statement \
  --plugin charles-schwab \
  --plugins-dir plugins \
  --input tests/e2e-data/charles-schwab/input-taxable-mixed.csv \
  --portfolio tests/e2e-data/charles-schwab/portfolio.json \
  --import-log tests/e2e-data/charles-schwab/import_log.jsonl \
  --write
```

Run the same command twice to verify idempotency (`inserted=0`, `skipped>0` on second run).

The taxable fixture intentionally includes a EUR account. `fx_rates.jsonl` pins the
EUR->USD conversion used by automated E2E tests so the importer is checked for row
currency preservation while aggregation is checked for USD base-currency conversion.
Negative fixtures are covered by automated tests and should fail with validation errors.
