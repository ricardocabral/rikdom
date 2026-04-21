# ibkr_flex_xml

Pluggy `source/input` plugin that imports activities from Interactive Brokers Flex XML statements.

## Expected Input

- XML from IBKR Flex (`FlexQueryResponse` / `FlexStatement`)
- Uses `Trade` and `CashTransaction` rows
- Supports compact IBKR date formats (for example `YYYYMMDD;HHMMSS`)

## Mapping Notes

- `provider` is always `ibkr_flex_xml`
- `generated_at` is normalized to UTC ISO-8601 when available
- `Trade` rows map to `buy` / `sell` (fallback `trade`)
- `CashTransaction` rows map to `dividend`, `interest`, `fee`, `tax`, `transfer_in`, `transfer_out` (fallback `cash`)
- Duplicate IDs are de-duplicated and cancel-like trade rows are skipped

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin ibkr_flex_xml \
  --plugins-dir plugins \
  --input tests/fixtures/ibkr_flex_statement_sample.xml \
  --portfolio tests/fixtures/portfolio.json
```
