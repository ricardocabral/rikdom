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

## Received income and replay

CSV dividend/interest and OFX `INCOME` (`DIV`/`INTEREST`) amounts preserve source
signs, including corrections and explicit zero. Neither format's supported cash
amount establishes gross/net, so income declares
`metadata.rikdom_income = {"version": 1, "amount_basis": "unknown"}`. CSV income
fees retain signs and explicit zero in the transaction currency; missing charges
remain unreported. Explicit invalid CSV transaction currencies are rejected;
omitted CSV currencies retain the existing USD default. An explicit invalid OFX
`CURDEF` currency is also rejected; omitted `CURDEF` retains the USD default.

CSV withholding, `Tax`, `Taxes`, `Tax Withheld` and `Tax Refund` actions map to
separate signed `tax_withheld` events before dividend/interest matching. No tax
rows are linked to dividends. Richer attached tax/fee-currency or explicit
net/gross evidence requires reviewed `normalized-statement-json` input.
Unsupported OFX income types/transactions remain in diagnostics; this importer
does not recover tax payments from arbitrary OFX expense/memo text. Explicit
malformed OFX income `TOTAL` values raise rather than disappear from mixed input.

Existing IDs and idempotency keys retain their legacy calculation even where
old versions normalized negative income to positive. Conflicting CSV identities
or OFX FITIDs fail rather than silently discard signed corrections. Anonymous
legacy fingerprint collisions also fail. Source identity metadata lets preflight
require review of a conflicting stored legacy event; record an auditable
canonical correction instead of overwriting it. Unchanged output replays without
inserting or updating events.
