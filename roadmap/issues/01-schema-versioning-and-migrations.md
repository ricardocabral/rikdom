# Schema Versioning + Migration Toolkit

## Parent PRD

Initial rikdom PRD (Codex thread, 2026-04-20)

## What to build

Add explicit migration docs and scripts to move portfolio files across schema versions with backward-compatible defaults and validation reports.

## Acceptance criteria

- [ ] `docs/migrations.md` defines compatibility policy.
- [ ] `scripts/migrate_portfolio.py` migrates at least `1.0.0 -> 1.1.0`.
- [ ] Migration run reports changed fields and unknown-field preservation.

## Blocked by

None - can start immediately.

## User stories addressed

- Durable schema evolution over years.
- Safe upgrades without data loss.
