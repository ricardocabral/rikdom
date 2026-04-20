# Migration CLI For Schema Upgrades

## Parent PRD

Initial rikdom PRD (Codex thread, 2026-04-20)

## What to build

Provide migration tooling to transform older portfolio files into newer schema versions while preserving unknown metadata/extensions.

## Acceptance criteria

- [ ] Migration script supports at least one forward upgrade path.
- [ ] Dry-run mode shows changes without writing.
- [ ] Backup strategy is documented before write operations.

## Blocked by

- Blocked by #1.

## User stories addressed

- Durable data across schema changes.
