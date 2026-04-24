# charles-schwab

Pluggy `source/input` plugin that imports Charles Schwab CSV statement exports into Rikdom canonical statement JSON.

## Supported Input (v1)

Single CSV containing mixed record types with this header set:

- `record_type` (`account`, `position`, `cash`, `transaction`)
- `account_number`, `account_name`, `statement_date`, `currency`
- Position rows: `security_type`, `symbol`, `description`, `quantity`, `market_value`
- Cash rows: `cash_balance`
- Transaction rows: `date`, `action`, `symbol`, `description`, `quantity`, `amount`, `fees`, `reference_id`

Header matching is case-insensitive and tolerant of spaces/punctuation.

## Mapping Notes

- `provider` is always `charles-schwab`
- `metadata.accounts` captures account metadata discovered in the file
- Position + cash rows map to canonical `holdings`
- Transaction rows map to canonical `activities`
- Supported transaction mappings: `buy`, `sell`, `dividend`, `interest`, `fee`, `transfer_in`, `transfer_out` (fallback `other`)
- Deterministic `id`/`idempotency_key` values are generated for idempotent re-runs

## Known Gaps (v1)

- No PDF parsing
- No OFX support yet
- No advanced corporate-action expansion (splits, mergers, spin-offs)
- Assumes U.S. jurisdiction defaults for instruments unless additional fields are provided

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin charles-schwab \
  --plugins-dir plugins \
  --input plugins/charles-schwab/fixtures/taxable-mixed/input.csv \
  --portfolio tests/fixtures/portfolio.json
```

## E2E Runner (isolated portfolio workspace)

Run from repo root:

```bash
plugins/charles-schwab/run-e2e.sh
```

- Uses a temporary portfolio directory under `/tmp` (does not touch `data/`)
- Imports twice to verify idempotency
- Set `KEEP_E2E_DIR=1` to keep generated artifacts for inspection
