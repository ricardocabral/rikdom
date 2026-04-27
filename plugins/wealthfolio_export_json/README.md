# wealthfolio_export_json

Pluggy `source/input` plugin that imports holdings and activities from a Wealthfolio JSON export.

## Expected Input

JSON exported from Wealthfolio (`Settings → Export Data`). The plugin recognizes:

- `activities` (or `transactions`) — typed events with `activity_type`, `activity_date`,
  `quantity`, `unit_price`, `currency`, `fee`, `is_draft`, `account_id`, `asset_id`.
- `holdings` (or `positions`) — current snapshot rows with `asset_id`, `quantity`,
  `market_value`, and `currency`.
- `assets` — asset metadata used to enrich rows missing `currency`, `name`, or `ticker`.

Top-level arrays, the `data`/`result`/`export` envelope, and per-account groupings are
all supported.

## Activity Type Mapping

`BUY`/`SELL`/`DIVIDEND`/`INTEREST`/`SPLIT` map directly. `DEPOSIT`/`WITHDRAWAL`,
`TRANSFER_IN`/`TRANSFER_OUT`, `CONVERSION_IN`/`CONVERSION_OUT`, and
`ADD_HOLDING`/`REMOVE_HOLDING` map to the canonical `transfer_in`/`transfer_out` events.
Unknown types fall back to `event_type=other` with `subtype=wealthfolio:<raw>`.

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin wealthfolio_export_json \
  --plugins-dir plugins \
  --input tests/fixtures/wealthfolio_export_sample.json \
  --portfolio tests/fixtures/portfolio.json
```
