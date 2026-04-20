# Skill: rikdom portfolio analyst (Codex)

## Purpose

Help users inspect, evolve, and analyze durable local-first portfolio JSON files.

## Inputs

- `data/portfolio.json`
- `data/snapshots.jsonl`
- `schema/*.json`

## Rules

1. Validate first with `rikdom validate`.
2. When adding new asset fields, prefer `metadata` or `extensions` before changing core fields.
3. If a new field is broadly useful, propose a schema bump with migration notes.
4. Keep recommendations country-aware using `asset_type_catalog[*].availability.countries`.

## Typical Tasks

- Allocation and concentration analysis
- Drawdown and growth trend review from snapshots
- Schema extension proposal with backward compatibility notes
- Import troubleshooting for community plugins
