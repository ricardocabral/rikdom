# Storage Model

## Principle

Local directory storage in plain text files for long-term resilience.

## Files

- `data/portfolio.json`
  - Current portfolio truth.
  - Edited manually or via imports.
  - Can include recurring operational workflows in `operations.task_catalog` and `operations.task_events`.
- `data/snapshots.jsonl`
  - Append-only history.
  - One JSON object per line.
- `schema/*.json`
  - Validation and interoperability contracts.

## Why JSON + JSONL

- Ubiquitous tooling support.
- Easy Git diff/merge for collaborative history.
- Survives framework/runtime churn.
- Friendly to LLM ingestion and deterministic parsing.

## Backup Strategy

- Commit data/schema changes to Git frequently.
- Optional periodic encrypted backups of `data/`.
- Keep plugin import fixtures for auditability.
