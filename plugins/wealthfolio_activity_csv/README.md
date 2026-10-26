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
