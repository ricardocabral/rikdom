# Import Pipeline: Idempotency + Provenance

## Parent PRD

Initial rikdom PRD (Codex thread, 2026-04-20)

## What to build

Upgrade imports to capture deterministic provenance (`source_system`, `source_ref`, `import_run_id`, `idempotency_key`, `ingested_at`) and deduplicate re-imported data safely.

## Acceptance criteria

- [ ] Duplicate import runs do not create duplicate economic events.
- [ ] Import logs expose inserted/updated/skipped counts.
- [ ] Provenance fields are persisted and queryable.

## Blocked by

- Blocked by #1.

## User stories addressed

- Trustworthy recurring imports.
- Auditability of imported statements.
