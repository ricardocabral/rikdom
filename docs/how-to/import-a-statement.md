# Import a broker statement

Use this guide to ingest a provider statement into your `data/portfolio.json`
through a `source/input` plugin. For the full plugin model, see
[plugin architecture](../explanation/plugin-architecture.md).

## Discover available importers

```bash
uv run rikdom plugins list --plugins-dir plugins
```

Statement importers shipped in this repo:

- `csv-generic` — generic CSV statements.
- `ghostfolio_export_json` — Ghostfolio JSON exports.
- `ibkr_flex_xml` — Interactive Brokers Flex XML.
- `charles-schwab` — Charles Schwab CSV exports.
- `b3-consolidado-mensal` — B3 consolidated monthly XLSX.

Each plugin's README documents its expected file format.

## Dry-run an import

Always preview first:

```bash
uv run rikdom import-statement \
  --plugin csv-generic \
  --input path/to/statement.csv \
  --data-dir data --out-root out \
  --dry-run
```

Dry-run prints the merge plan without writing to `data/portfolio.json` or
appending to `data/import_log.jsonl`.

## Write the import

```bash
uv run rikdom import-statement \
  --plugin csv-generic \
  --input path/to/statement.csv \
  --data-dir data --out-root out \
  --write
```

Behavior:

- `data/portfolio.json` is updated using atomic write (see
  [storage durability](../explanation/storage-durability.md)).
- One row is appended to `data/import_log.jsonl` with the `source_system`,
  `source_ref`, `import_run_id`, and `idempotency_key` for the run.
- Repeats are deduplicated by `idempotency_key` — re-running the same
  import is a no-op.

## Validate the result

```bash
uv run rikdom validate --data-dir data --out-root out
```

Inspect any reconciliation findings — see
[reconciliation codes reference](../reference/reconciliation-codes.md).

## Write your own importer

See [author your first plugin](../tutorials/first-plugin.md).

## See also

- [Plugin architecture](../explanation/plugin-architecture.md)
- [Plugin hooks reference](../reference/plugin-hooks.md)
- [CLI reference: plugins](../reference/cli.md#plugins)
