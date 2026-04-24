# vanguard

Pluggy `source/input` plugin that imports Vanguard CSV statement exports into Rikdom canonical statement JSON.

## Supported Input (v1)

### 1) CSV (mixed record export)

Single CSV containing mixed record types with this header set:

- `record_type` (`account`, `position`, `cash`, `transaction`)
- `account_number`, `account_name`, `account_type`, `statement_date`, `currency`
- Position rows: `security_type`, `symbol`, `isin`, `description`, `quantity`, `market_value`
- Cash rows: `cash_balance`
- Transaction rows: `date`, `activity_type`, `symbol`, `description`, `quantity`, `amount`, `fees`, `reference_id`

Header matching is case-insensitive and tolerant of spaces/punctuation.

### 2) OFX/QFX (investment statement)

Supports OFX investment statement sections used by Vanguard exports, including:

- account metadata (`INVACCTFROM`, `CURDEF`)
- securities (`SECLIST` / `SECINFO`)
- positions (`POSMF`, `POSSTOCK`, `POSDEBT`, `POSOTHER`)
- cash (`INVBAL/AVAILCASH`)
- transactions in `INVTRANLIST`:
  - buys/sells (`BUY*`, `SELL*`)
  - income (`INCOME` with `DIV`/`INTEREST`)
  - expenses (`INVEXPENSE`)

## Mapping Notes

- `provider` is always `vanguard`
- `metadata.accounts` captures account metadata discovered in the file
- Position + cash rows map to canonical `holdings`
- Transaction rows map to canonical `activities`
- Supported transaction mappings: `buy`, `sell`, `dividend`, `interest`, `fee`, `transfer_in`, `transfer_out` (fallback `other`)
- Deterministic `id`/`idempotency_key` values are generated for idempotent re-runs

## Known Gaps (v1)

- No PDF parsing
- OFX support is focused on common Vanguard investment sections (not every OFX variant/corporate-action type)
- No tax-lot/cost-basis reconstruction
- Assumes U.S. jurisdiction defaults for instruments unless additional fields are provided

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin vanguard \
  --plugins-dir plugins \
  --input plugins/vanguard/fixtures/etf-heavy/input.csv \
  --portfolio tests/fixtures/portfolio.json

# OFX example
uv run rikdom import-statement \
  --plugin vanguard \
  --plugins-dir plugins \
  --input plugins/vanguard/fixtures/ofx-brokerage/input.ofx \
  --portfolio tests/fixtures/portfolio.json
```
