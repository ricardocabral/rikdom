# Charles Schwab E2E data folder

This folder contains a clean workspace for end-to-end import tests with the `charles-schwab` plugin.

## Files

- `portfolio.json`: clean canonical portfolio for repeatable imports
- `snapshots.jsonl`: optional snapshot ledger (empty by default)
- `fx_rates.jsonl`: optional FX history (empty by default)
- `import_log.jsonl`: optional import log (empty by default)
- `input-taxable-mixed.csv`: taxable account fixture
- `input-ira-income.csv`: IRA fixture

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
