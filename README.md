# rikdom

Portable, local-first wealth portfolio schema + storage toolkit.

`rikdom` is designed so your portfolio data can last for years as plain JSON files, independent of any broker app or SaaS dashboard.

## What It Solves

- Define a portfolio for a person or company.
- Track holdings across stocks, REITs, funds, real estate, cash equivalents, digital assets and cryptocurrencies.
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

### 1. Install in editable mode

```bash
python3 -m pip install -e .
```

### 2. Validate the portfolio file

```bash
rikdom validate --portfolio data/portfolio.json
```

### 3. Aggregate by asset class

```bash
rikdom aggregate --portfolio data/portfolio.json
```

### 4. Append a historical snapshot

```bash
rikdom snapshot --portfolio data/portfolio.json --snapshots data/snapshots.jsonl
```

### 5. Generate dashboard

```bash
rikdom visualize --portfolio data/portfolio.json --snapshots data/snapshots.jsonl --out out/dashboard.html --include-current
```

## Schema Docs

- [Schema design](docs/schema-design.md)
- [Storage model](docs/storage.md)
- [Visualization module](docs/visualization.md)

## Community Plugins

Plugin docs and example parser:

- [plugins/README.md](plugins/README.md)
- `plugins/community/csv-generic`

Use:

```bash
rikdom import-statement \
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
