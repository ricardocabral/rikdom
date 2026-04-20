# Community Import Plugins

`rikdom` uses local plugins to convert provider statements into normalized JSON holdings.

## Goals

- Keep the core schema stable and provider-agnostic.
- Let community plugins evolve quickly without breaking the base format.
- Keep imports transparent: plugin input/output is plain files and JSON.

## Directory Layout

- `plugins/community/<plugin-name>/plugin.json`
- `plugins/community/<plugin-name>/...` parser scripts

## `plugin.json` Format

```json
{
  "name": "csv-generic",
  "version": "0.1.0",
  "description": "Parse a generic CSV statement",
  "command": ["python3", "importer.py"]
}
```

- `command` is executed in the plugin directory.
- The CLI appends the input file path as the final argument.

## Plugin Output Contract

Plugin stdout must be JSON matching `schema/plugin-statement.schema.json`.

Minimal shape:

```json
{
  "provider": "example",
  "generated_at": "2026-04-20T12:00:00Z",
  "holdings": [
    {
      "id": "provider-asset-1",
      "asset_type_id": "stock",
      "label": "Asset Name",
      "market_value": { "amount": 1234.56, "currency": "USD" }
    }
  ]
}
```

## Running Imports

```bash
rikdom import-statement \
  --portfolio data/portfolio.json \
  --plugin csv-generic \
  --input data/sample_statement.csv \
  --write
```

## Contribution Guidelines

- Keep plugins deterministic and idempotent.
- Prefer stable IDs from provider/account/ticker combinations.
- Include fixture files and tests when practical.
- Never include credentials in plugin code.
