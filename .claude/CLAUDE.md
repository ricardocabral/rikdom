# Claude Instructions For Rikdom

You are working on a local-first wealth portfolio schema project.

## Primary Objectives

- Keep user financial data portable and readable as plain JSON/JSONL.
- Avoid lock-in to any broker, SaaS, or visualization stack.
- Preserve backward compatibility across schema versions whenever possible.
- Keep plugin behavior deterministic, auditable, and easy to reason about.

## Read Order For Context

1. `README.md`
2. `docs/plugin-system.md`
3. `plugins/README.md`
4. `src/rikdom/cli.py`
5. `src/rikdom/plugin_engine/*`
6. `src/rikdom/plugins.py` (legacy import path)

## Plugin System: Current Reality (Important)

The repo is currently hybrid:

- `import-statement` CLI path uses legacy subprocess plugins via `src/rikdom/plugins.py` and `plugin.json.command`.
- `render-report`, `storage-sync`, and asset-type catalog plumbing use the Pluggy engine in `src/rikdom/plugin_engine/`.

Do not assume all plugin types are wired into CLI entrypoints yet.

## Plugin Layout And Contracts

- Plugin folder: `plugins/<plugin-name>/`
- Required file: `plugins/<plugin-name>/plugin.json`
- Manifest required fields: `name`, `version`
- Pluggy plugins should also define: `plugin_types`, `module`, `class_name`
- Legacy import plugins may define `command` for subprocess execution

Source of truth for taxonomy:
- `src/rikdom/plugin_engine/contracts.py` (`PhaseName`)

Source of truth for hooks:
- `src/rikdom/plugin_engine/hookspecs.py`

Dispatch semantics:
- `firstresult=True`: `source_input`, `output`, `state_storage_sync`, `state_storage_query`, `state_storage_health`
- Fan-out: `asset_type_catalog`, `observability`, `audit_trail`

## Guardrails

- Do not introduce opaque binary formats for canonical state.
- Do not require cloud services for core functionality.
- Preserve unknown fields under `metadata` and `extensions`.
- Keep plugin runs deterministic and idempotent.
- Treat plugin code as trusted local code with potential side effects.
- Do not commit secrets in plugin manifests or code.

## Working Rules

- Use `uv run` for all project commands and tests.
- For plugin changes, update tests and docs together.
- If touching manifests or engine contracts, verify:
  - `uv run rikdom plugins list --plugins-dir plugins`
  - relevant tests in `tests/`
- Keep behavior explicit; avoid hidden magic or implicit network dependencies.

## Common Commands

```bash
uv run rikdom validate --portfolio data/portfolio.json
uv run rikdom aggregate --portfolio data/portfolio.json
uv run rikdom snapshot --portfolio data/portfolio.json --snapshots data/snapshots.jsonl
uv run rikdom visualize --portfolio data/portfolio.json --snapshots data/snapshots.jsonl --out out/dashboard.html --include-current
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom import-statement --plugin csv-generic --input data/sample_statement.csv --portfolio data/portfolio.json
uv run rikdom render-report --plugin quarto-portfolio-report --plugins-dir plugins
uv run rikdom storage-sync --plugin duckdb-storage --plugins-dir plugins
uv run rikdom migrate --portfolio data/portfolio.json --dry-run
uv run rikdom migrate --portfolio data/portfolio.json
```

See `docs/migrations.md` for the migration authoring guide and backup strategy.
