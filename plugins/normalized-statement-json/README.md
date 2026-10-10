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
