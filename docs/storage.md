# Storage Model

## Principle

Local directory storage in plain text files for long-term resilience.

## Files

- `data/portfolio.json`
  - Current portfolio truth in your local workspace.
  - Auto-seeded from `data-sample/portfolio.json` when running CLI defaults and file is missing.
  - Edited manually or via imports.
  - Can include recurring operational workflows in `operations.task_catalog` and `operations.task_events`.
- `data/snapshots.jsonl`
  - Append-only local history.
  - Auto-seeded from `data-sample/snapshots.jsonl` when running CLI defaults and file is missing.
  - One JSON object per line.
- `data/import_log.jsonl`
  - Append-only local import audit trail for `import-statement --write`.
- `data-sample/portfolio.json` and `data-sample/snapshots.jsonl`
  - Tracked starter templates committed with the repository.
- `schema/*.json`
  - Validation and interoperability contracts.

## Why JSON + JSONL

- Ubiquitous tooling support.
- Easy Git diff/merge for collaborative history.
- Survives framework/runtime churn.
- Friendly to LLM ingestion and deterministic parsing.

## Backup Strategy

- Commit `schema/` and `data-sample/` updates to Git when templates/contracts change.
- Optional periodic encrypted backups of local `data/`.
- Keep plugin import fixtures for auditability.
