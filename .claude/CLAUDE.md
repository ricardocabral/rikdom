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

- Prefer `make <target>` for routine local workflows; keep `uv run ...` for targeted debugging or when a target does not exist yet.
- Use `uv run` for all project commands and tests.
- On clean checkouts, bootstrap local `data/*` files from tracked `data-sample/*` before running commands that reference `data/*`.
- For plugin changes, update tests and docs together.
- If touching manifests or engine contracts, verify:
  - `uv run rikdom plugins list --plugins-dir plugins`
  - relevant tests in `tests/`
- Keep behavior explicit; avoid hidden magic or implicit network dependencies.

## Common Commands

Preferred task runner (mirrors `Makefile` targets):

```bash
make sync
make bootstrap
make validate
make validate-fixture
make aggregate
make snapshot
make visualize
make plugins-list
make import-sample
make render-report
make storage-sync
make migrate-dry-run
make lint
make test
make check
```

Direct command equivalents (useful for focused debugging):

```bash
uv sync --extra schema
uv run rikdom validate --data-dir data --out-root out
uv run rikdom validate --portfolio tests/fixtures/portfolio.json
uv run rikdom aggregate --data-dir data --out-root out
uv run rikdom snapshot --data-dir data --out-root out
uv run rikdom visualize --data-dir data --out-root out --include-current
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom import-statement --data-dir data --out-root out --plugin csv-generic --input data-sample/sample_statement.csv --write
uv run rikdom render-report --data-dir data --out-root out --plugin quarto-portfolio-report --plugins-dir plugins
uv run rikdom storage-sync --data-dir data --out-root out --plugin duckdb-storage --plugins-dir plugins
uv run rikdom migrate --portfolio data-sample/portfolio.json --dry-run
ruff check .
uv run python -m unittest discover -s tests -v
```

See `docs/migrations.md` for the migration authoring guide and backup strategy.
