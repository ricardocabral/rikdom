# Deterministic Valuation And FX Conversion Policy

## Parent PRD

Initial rikdom PRD (Codex thread, 2026-04-20)

## What to build

Define and implement deterministic valuation rules for mixed-currency holdings, including required metadata and clear warning/error handling when FX context is missing.

## Acceptance criteria

- [ ] `docs/valuation-policy.md` documents conversion precedence and required fields.
- [ ] CLI aggregation reports missing FX as structured warnings.
- [ ] Unit tests cover same-currency and cross-currency cases.

## Blocked by

- Blocked by #1 if schema fields need revision.

## User stories addressed

- Accurate aggregation over global asset sets.
- Portable analytics reproducibility.
