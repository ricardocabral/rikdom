# Skill: OpenAI Codex Portfolio Workflow

Use this when editing or analyzing rikdom portfolio data.

## Workflow

1. Read `README.md` and `docs/schema-design.md`.
2. Validate the portfolio with `rikdom validate`.
3. If producing aggregates, run `rikdom aggregate` and optionally `rikdom visualize`.
4. For schema changes, update:
   - `schema/portfolio.schema.json`
   - `docs/schema-design.md`
   - `README.md`
5. Keep changes backward-compatible whenever possible.

## Output Expectations

- Explicitly state assumptions.
- Include any warnings about missing FX conversion.
- Reference updated file paths.
