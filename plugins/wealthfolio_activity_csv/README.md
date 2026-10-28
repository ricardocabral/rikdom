# wealthfolio_activity_csv

Pluggy `source/input` plugin that imports Wealthfolio activities from the activity CSV
format. This is the fallback path when a JSON export is unavailable; prefer
[`wealthfolio_export_json`](../wealthfolio_export_json/README.md) when possible.

## Expected Input

CSV exported by Wealthfolio (`Activities → Export CSV`) with header columns such as:

- `date` (ISO 8601 or `YYYY-MM-DD`)
- `symbol` (or `ticker`)
- `quantity`, `unit_price`, `amount` (any of these may be present)
- `currency`
- `activity_type` (BUY, SELL, DIVIDEND, INTEREST, DEPOSIT, WITHDRAWAL, FEE, …)
- `fee`
- `account_id`, `comment`, `is_draft`, `id`

The delimiter is detected from the header. The semicolon dialect uses comma
decimals and dot grouping; the comma, tab and pipe dialects use dot decimals
and comma grouping. Numeric values never select their own locale. Dates use
ISO 8601; dates without a timezone use UTC.

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin wealthfolio_activity_csv \
  --plugins-dir plugins \
  --input tests/fixtures/wealthfolio_activities_sample.csv \
  --portfolio tests/fixtures/portfolio.json
```

## Received income semantics

`INCOME` maps to generic `income`, separately from known `DIVIDEND` and `INTEREST`.
Source tax and tax-refund events map to `tax_withheld`; signed amounts and IDs are
preserved without linking standalone taxes to income rows.

An explicit income amount is marked
`metadata.rikdom_income = {"version": 1, "amount_basis": "net"}`. Wealthfolio's
[official Activity Fields documentation](https://wealthfolio.app/docs/concepts/activity-fields/)
defines Amount as the final cash received, with fees and taxes already included.
The source `tax` field becomes `withholding_tax`; fees/taxes retain signs and
explicit zeros in the activity currency. Missing withholding remains unknown.
Legacy quantity/price-derived income remains supported with basis `unknown`:
those fields alone do not establish a final cash amount. Invalid supplied money
fails visibly instead of falling back to a derived amount.

Existing unmarked canonical activities need reimport or explicit correction to
acquire basis evidence. The importer does not migrate stored portfolios or claim
all historical Wealthfolio export versions have identical semantics.

For anonymous CSV rows, the newly supported `tax` column is excluded from the
legacy ID hash so reimport enriches the existing row. Rows that differ only in
tax retain the legacy identity collision; supply stable source IDs to distinguish
them.
