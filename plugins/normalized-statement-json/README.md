# Normalized JSON statements

Imports `schema/plugin-statement.schema.json` payloads produced by reviewed
recovery work or another system. Supports holdings, activities and tax lots.
JSON Schema validation includes date formats before portfolio mutation.

```bash
uv run rikdom import-statement --data-dir data \
  --plugin normalized-statement-json --input statement.json --dry-run
```

Use `--write` to apply the displayed merge. Preserve stable event and lot IDs,
source references, and explicit partial-history declarations. Schema validation
does not prove that external source data or historical coverage is complete.

See [FII history conventions](../../docs/reference/fii-history.md).

Income is canonical passthrough: signed amounts, independent charge currencies,
explicit zeros, absent fields and caller metadata are retained. Income markers
use `metadata.rikdom_income = {"version": 1, "amount_basis": "gross"|"net"|"unknown"}`.
Without a marker the canonical schema's gross-amount convention applies. Choose
`unknown` when source evidence does not establish gross/net; schema validity
alone cannot establish the amount basis. Standalone `tax_withheld` events remain
separate and are not counted as received dividends or interest.
