# vanguard

Pluggy `source/input` plugin that imports Vanguard CSV statement exports into Rikdom canonical statement JSON.

## Supported Input (v1)

Single CSV containing mixed record types with this header set:

- `record_type` (`account`, `position`, `cash`, `transaction`)
- `account_number`, `account_name`, `account_type`, `statement_date`, `currency`
- Position rows: `security_type`, `symbol`, `isin`, `description`, `quantity`, `market_value`
- Cash rows: `cash_balance`
- Transaction rows: `date`, `activity_type`, `symbol`, `description`, `quantity`, `amount`, `fees`, `reference_id`

Header matching is case-insensitive and tolerant of spaces/punctuation.

## Mapping Notes

- `provider` is always `vanguard`
- `metadata.accounts` captures account metadata discovered in the file
- Position + cash rows map to canonical `holdings`
- Transaction rows map to canonical `activities`
- Supported transaction mappings: `buy`, `sell`, `dividend`, `interest`, `fee`, `transfer_in`, `transfer_out` (fallback `other`)
- Deterministic `id`/`idempotency_key` values are generated for idempotent re-runs

## Known Gaps (v1)

- No PDF parsing
- No OFX support yet
- No tax-lot/cost-basis reconstruction
- Assumes U.S. jurisdiction defaults for instruments unless additional fields are provided

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin vanguard \
  --plugins-dir plugins \
  --input plugins/vanguard/fixtures/etf-heavy/input.csv \
  --portfolio tests/fixtures/portfolio.json
```
