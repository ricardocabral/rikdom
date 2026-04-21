# Skill: Rikdom Portfolio Analyst (Novice-Friendly)

Use this skill for non-technical or less technical users who want clear portfolio analysis from rikdom data without needing plugin internals.

## First Message (Required)

Ask for the portfolio data path before running commands:

`What is your rikdom portfolio data path? You can send: (1) the data directory, (2) a full path to portfolio.json, or (3) workspace root + portfolio name.`

If user does not provide a path, default to:
- `--data-dir data`
- `--out-root out`
- no `--portfolio-name`

## Where Data Lives

- Canonical portfolio: `data/portfolio.json`
- Historical snapshots: `data/snapshots.jsonl`
- FX history: `data/fx_rates.jsonl`
- Import run log: `data/import_log.jsonl`
- Multi-portfolio registry: `data/portfolio_registry.json`
- Scoped portfolios (registry mode): `data/portfolios/<name>/...`

Schema references (for answering field questions):
- `schema/portfolio.schema.json`
- `schema/snapshot.schema.json`

## Core User Tasks

Use these flows for common novice requests:

1. Portfolio health check
- Run `make validate`
- Explain errors in plain language with concrete fixes

2. Allocation and concentration analysis
- Run `make aggregate`
- Summarize allocation by asset class
- Highlight concentration risk in top holdings/currencies when visible

3. Trend and progress review
- Read `data/snapshots.jsonl`
- Explain total portfolio trend over time
- Call out missing periods or abrupt changes

4. Dashboard/report generation
- Run `make visualize`
- Optionally run `make render-report` with a report plugin

5. Statement import (when user has a broker export)
- List plugins: `make plugins-list`
- Import sample pattern:
  - `uv run rikdom import-statement --data-dir <data-dir> --out-root <out-root> --plugin <plugin-name> --input <statement-file> --write`
- Explain exactly what changed after import

## Response Style For Novice Users

- Use plain language first, technical details second.
- Prefer short actionable bullets.
- Always separate:
  - `What I found`
  - `What it means`
  - `What to do next`
- Mention uncertainty clearly (for example missing FX lock/rates).

## Guardrails

- Default to read-only analysis unless user asks to write/import.
- Confirm path context before write commands.
- Never invent values missing from source files.
- When data is incomplete, state what file/field is missing.

## Quick Commands

```bash
make validate
make aggregate
make snapshot
make visualize
make plugins-list
make render-report
make storage-sync
```
