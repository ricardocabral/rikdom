# Skill: Rikdom Portfolio Workflow (Codex)

Use this when editing or analyzing rikdom portfolio data.

## Inputs

- `data/portfolio.json`
- `data/snapshots.jsonl`
- `schema/*.json`

## Workflow

1. Read `README.md` and `docs/schema-design.md`.
2. Validate first with `uv run rikdom validate --portfolio data/portfolio.json`.
3. For aggregates or trend analysis, run `uv run rikdom aggregate` and optionally `uv run rikdom visualize`.
4. When adding new asset fields, prefer `metadata` or `extensions` before changing core fields.
5. For broadly useful fields, propose a schema version bump with migration notes.
6. Keep changes backward-compatible whenever possible.

## Output Expectations

- Explicitly state assumptions.
- Include warnings when valuation may be impacted by missing FX conversion.
- Reference updated file paths.
