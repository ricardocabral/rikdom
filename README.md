# rikdom

Portable, local-first wealth portfolio schema + storage toolkit.

`rikdom` is designed so your portfolio data can last for years as plain JSON files, independent of any broker app or SaaS dashboard.

## What It Solves

- Define a portfolio for a person or company.
- Track holdings across stocks, REITs, funds, real estate, cash equivalents, digital assets and cryptocurrencies.
- Model recurring operations (monthly/yearly tasks) and keep an auditable "last done" history.
- Extend asset types with country-specific classes and metadata.
- Persist data in simple disk files (`JSON` + `JSONL`).
- Generate a minimal static dashboard for allocation and progress over time.
- Ingest provider statements through community plugins.

## Core Principles

- Local-first: data stays in your folder.
- Durable formats: JSON schema and line-delimited snapshots.
- Extensible by design: `metadata` and `extensions` fields.
- Agent-friendly: explicit schema + instructions for Codex/Claude.

## Repository Structure

- `schema/` JSON schemas and default asset types
- `data/` sample portfolio and snapshots
- `src/rikdom/` Python CLI and visualization module
- `plugins/` community import plugin interface + examples
- `agents/` AI agent skills/instruction files
- `plans/` implementation plan
- `roadmap/issues/` issue specs for GitHub roadmap

## Quick Start

### 1. Install uv

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for your platform.

### 2. Sync dependencies with uv

```bash
uv sync --extra schema
```

### 3. Validate the portfolio file

```bash
uv run rikdom validate --portfolio data/portfolio.json
```

### 4. Aggregate by asset class

```bash
uv run rikdom aggregate --portfolio data/portfolio.json
```

### 5. Append a historical snapshot

```bash
uv run rikdom snapshot --portfolio data/portfolio.json --snapshots data/snapshots.jsonl
```

### 6. Generate dashboard

```bash
uv run rikdom visualize --portfolio data/portfolio.json --snapshots data/snapshots.jsonl --out out/dashboard.html --include-current
```

## Schema Docs

- [Schema design](docs/schema-design.md)
- [Storage model](docs/storage.md)
- [Visualization module](docs/visualization.md)

## Community Plugins

Plugin docs and example parser:

- [plugins/README.md](plugins/README.md)
- `plugins/csv-generic`

Use:

```bash
uv run rikdom import-statement \
  --portfolio data/portfolio.json \
  --plugin csv-generic \
  --input data/sample_statement.csv \
  --write
```

## AI Agent Skills

- `agents/codex/SKILL.md`
- `agents/openai-codex/SKILL.md`
- `agents/claude/CLAUDE.md`

These files guide LLM agents to safely analyze and evolve your data model.

## Roadmap And Planning

- [Implementation plan](plans/rikdom-implementation-plan.md)
- GitHub issue specs in `roadmap/issues/`
- Script to publish issue specs: `scripts/create_github_issues.py`

## License

MIT (see `LICENSE`).
