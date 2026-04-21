# Skill: Rikdom Portfolio Workflow (Codex)

Use this when editing or analyzing rikdom portfolio data and plugin behavior.

## Core Context

- Canonical data is local-first and file-based (`JSON` + `JSONL`).
- Primary runtime entrypoint is `src/rikdom/cli.py`.
- Plugin system is currently hybrid:
  - Legacy import path: `src/rikdom/plugins.py` (`plugin.json.command`, subprocess execution).
  - Pluggy engine path: `src/rikdom/plugin_engine/*` (report/storage/catalog pipelines).

Do not assume `import-statement` uses Pluggy yet.

## Bootstrap (Clean Checkout)

Before running any command that references `data/*`, seed local workspace files from tracked samples:

```bash
mkdir -p data
[ -f data/portfolio.json ] || cp data-sample/portfolio.json data/portfolio.json
[ -f data/snapshots.jsonl ] || cp data-sample/snapshots.jsonl data/snapshots.jsonl
[ -f data/sample_statement.csv ] || cp data-sample/sample_statement.csv data/sample_statement.csv
```

## Inputs

- `data/portfolio.json`
- `data/snapshots.jsonl`
- `schema/*.json`
- `plugins/*/plugin.json`
- `src/rikdom/plugin_engine/*`

## Workflow

1. Read `README.md`, `docs/schema-design.md`, and `docs/plugin-system.md`.
2. For plugin work, also read `plugins/README.md` and `src/rikdom/cli.py` to confirm active CLI wiring.
3. Use `uv run` as the default launcher for `rikdom`, tests, and ad-hoc scripts.
4. Validate baseline behavior first:
   - `uv run rikdom validate --portfolio data/portfolio.json`
   - `uv run rikdom plugins list --plugins-dir plugins`
5. Match implementation to execution path:
   - `import-statement` changes: verify legacy command/plugin behavior and `tests/test_plugins.py`.
   - `render-report` / `storage-sync` / catalog changes: verify Pluggy pipeline behavior and plugin-engine tests.
6. Keep plugin behavior deterministic, explicit, and auditable.
7. When adding asset fields, prefer `metadata` or `extensions` before changing core schema fields.
8. For broadly useful schema fields, propose version bump + migration notes.
9. Keep changes backward-compatible whenever possible.

## Plugin Contract Notes

- Manifest required: `name`, `version`.
- Pluggy manifests should include: `plugin_types`, `module`, `class_name`.
- Legacy import manifests may include `command`.
- Plugin taxonomy source: `src/rikdom/plugin_engine/contracts.py` (`PhaseName`).
- Hook source: `src/rikdom/plugin_engine/hookspecs.py`.

Dispatch behavior:
- `firstresult=True` hooks choose one result (`source_input`, `output`, `state_storage_*`).
- Fan-out hooks aggregate all plugin calls (`asset_type_catalog`, `observability`, `audit_trail`).

## Validation Commands

```bash
uv run rikdom validate --portfolio data/portfolio.json
uv run rikdom aggregate --portfolio data/portfolio.json
uv run rikdom snapshot --portfolio data/portfolio.json --snapshots data/snapshots.jsonl
uv run rikdom visualize --portfolio data/portfolio.json --snapshots data/snapshots.jsonl --out out/dashboard.html --include-current
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom import-statement --plugin csv-generic --input data/sample_statement.csv --portfolio data/portfolio.json
uv run rikdom render-report --plugin quarto-portfolio-report --plugins-dir plugins
uv run rikdom storage-sync --plugin duckdb-storage --plugins-dir plugins
uv run python -m unittest discover -s tests -v
```

## Output Expectations

- State assumptions explicitly.
- Mention valuation caveats when FX conversion data is missing.
- Reference touched files and tests run.
