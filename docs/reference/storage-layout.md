# Storage Layout

Rikdom stores all canonical state in plain-text files inside a workspace
directory (default `data/`). For the durability rules, see
[storage durability](../explanation/storage-durability.md).

## Workspace files

| File | Kind | Written by | Purpose |
| --- | --- | --- | --- |
| `data/portfolio.json` | Whole doc | `import-statement --write`, `migrate` | Current portfolio truth. |
| `data/snapshots.jsonl` | Append-only JSONL | `snapshot` | Historical aggregated values. |
| `data/import_log.jsonl` | Append-only JSONL | `import-statement` | Import audit trail. |
| `data/fx_rates.jsonl` | Append-only JSONL | `snapshot` (auto-ingest), manual edits | FX history used at snapshot time. |
| `data/policy.json` | Whole doc | `migrate-policy`, manual edits | Investment Policy Statement (optional). |
| `data/portfolio_registry.json` | Whole doc | `workspace init` | Multi-portfolio registry (optional). |
| `data/portfolios/<name>/` | Directory | Workspace mode | Per-portfolio isolated data files. |

Files marked optional are absent from a fresh bootstrap; commands create them on first use.

## Tracked starter templates

`data-sample/portfolio.json` and `data-sample/snapshots.jsonl` are committed
to the repo and copied into `data/` on first default CLI run. `data/` itself
is gitignored.

## Schema files

`schema/*.json` carry the validation and interoperability contracts.
Documented in [schemas reference](schemas.md).

## Format choice

JSON + JSONL was chosen for:

- Ubiquitous tooling support (`cat`, `jq`, every language).
- Easy Git diff/merge for collaborative history.
- Survives framework/runtime churn — no proprietary serializers.
- Friendly to LLM ingestion and deterministic parsing.

## Backup

- Commit `schema/` and `data-sample/` updates to git when templates/contracts
  change.
- Optional periodic encrypted backups of local `data/`.
- Keep plugin import fixtures for auditability.

## See also

- [Storage durability](../explanation/storage-durability.md)
- [Schemas reference](schemas.md)
- [Recover from a crash](../how-to/recover-from-crash.md)
