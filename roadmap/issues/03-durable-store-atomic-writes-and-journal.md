# Durable Store: Atomic Writes + Journal Strategy

## Parent PRD

Initial rikdom PRD (Codex thread, 2026-04-20)

## What to build

Implement and document disk-write durability rules: atomic writes, append journal conventions, and snapshot compaction policy.

## Acceptance criteria

- [ ] Write strategy avoids partial/corrupted files on interruption.
- [ ] Journal format and rotation policy documented.
- [ ] Recovery workflow from journal/snapshot tested.

## Blocked by

None - can start immediately.

## User stories addressed

- Resilience to technology/runtime changes.
