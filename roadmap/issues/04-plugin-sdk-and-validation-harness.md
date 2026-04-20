# Plugin SDK + Validation Harness

## Parent PRD

Initial rikdom PRD (Codex thread, 2026-04-20)

## What to build

Provide a plugin SDK skeleton and automated validation harness so contributors can verify parser output against the statement schema before opening pull requests.

## Acceptance criteria

- [ ] `plugins/sdk/` template with manifest and parser scaffold.
- [ ] `scripts/check_plugin.py` validates output against schema.
- [ ] Contributor docs include fixture and expected-output workflow.

## Blocked by

None - can start immediately.

## User stories addressed

- Community-contributed import plugins.
- Reliable ingestion quality.
