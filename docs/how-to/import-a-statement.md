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
- `b3-consolidado-mensal` — B3 monthly holdings or `Movimentação` XLSX history.
- `irpf-xml` — Brazilian IRPF declaration XML (year-end holdings).

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
  --write --reconcile
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

## Check history and identity evidence

Import output includes `import_diagnostics` and a reconciliation summary for the
merged candidate. Unknown history is explicit. Successful writes retain source
coverage for future reports; previews leave the portfolio, run log, and artifacts
unchanged. `--reconcile` writes four JSON/Markdown trust artifacts after applying.

Canonical instrument keys come from source/regional plugins. Optional
`--collapse-canonical` requires an explicit matching account and unique candidate;
a shared ticker/key does not establish that two positions are the same holding.
Existing stored keys are preserved and never reminted automatically.

Anonymous overlapping source rows can block writing. Follow the
[reviewed identity recovery](../reference/import-diagnostics.md#reviewed-recovery)
path rather than assigning new IDs to every row. For manual events and immutable
corrections, see [enter and correct activities](enter-and-correct-activities.md).

B3 `Movimentação` history is supported alongside monthly holdings. Its synthetic
fixture reproduces the verified layout without any private source values. Movement
dates and institution names do not establish execution/settlement timing, account
identity, or complete history. Those gaps remain explicit; see the
[B3 plugin guide](../../plugins/b3-consolidado-mensal/README.md).
