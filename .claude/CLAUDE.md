# Claude Instructions For Rikdom

You are working on a local-first wealth portfolio schema project.

## Primary Objectives

- Keep user financial data portable and readable as plain JSON/JSONL.
- Avoid lock-in to any broker, SaaS, or visualization stack.
- Preserve backward compatibility across schema versions whenever possible.
- Keep plugin behavior deterministic, auditable, and easy to reason about.

## Read Order For Context

1. `README.md`
2. `docs/index.md` (Diataxis landing) and `docs/explanation/plugin-architecture.md`
3. `plugins/README.md`
4. `src/rikdom/cli.py`
5. `src/rikdom/plugin_engine/*`
6. `src/rikdom/plugins.py` (portfolio merge / provenance helpers)

## Plugin System: Current Reality (Important)

All plugins are Pluggy plugins loaded through `src/rikdom/plugin_engine/`.
There is no subprocess-style plugin path; the manifest schema rejects any
field outside the Pluggy set.

Do not assume all plugin types are wired into CLI entrypoints yet.

## Plugin Layout And Contracts

- Plugin folder: `plugins/<plugin-name>/`
- Required file: `plugins/<plugin-name>/plugin.json`
- Manifest required fields: `name`, `version`, `api_version`, `plugin_types`, `module`, `class_name`

Source of truth for taxonomy:
- `src/rikdom/plugin_engine/contracts.py` (`PhaseName`)

Source of truth for hooks:
- `src/rikdom/plugin_engine/hookspecs.py`

Dispatch semantics:
- `firstresult=True`: `source_input`, `output`, `state_storage_sync`, `state_storage_query`, `state_storage_health`, `connector_describe`, `connector_query`
- Fan-out: `asset_type_catalog`, `observability`, `audit_trail`

## Guardrails

- Do not introduce opaque binary formats for canonical state.
- Do not require cloud services for core functionality.
- Preserve unknown fields under `metadata` and `extensions`.
- Keep plugin runs deterministic and idempotent.
- Treat plugin code as trusted local code with potential side effects.
- Do not commit secrets in plugin manifests or code.
- Never commit PII in repository fixtures/samples (names, real account IDs, addresses, emails, phone numbers, government IDs, raw broker exports).
- Before committing fixture/sample files, sanitize to synthetic data and random identifiers/amounts.

## Working Rules

- Prefer `make <target>` for routine local workflows; keep `uv run ...` for targeted debugging or when a target does not exist yet.
- Use `uv run` for all project commands and tests.
- Run focused tests locally; use and monitor the pull request CI run for the full suite. See `CONTRIBUTING.md` for the testing workflow.
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
make viz
make plugins-list
make import-sample
make storage-sync
make migrate-dry-run
make lint
```

Direct command equivalents (useful for focused debugging):

```bash
uv sync --extra schema
uv run rikdom validate --data-dir data --out-root out
uv run rikdom validate --portfolio tests/fixtures/portfolio.json
uv run rikdom aggregate --data-dir data --out-root out
uv run rikdom snapshot --data-dir data --out-root out
uv run rikdom viz --data-dir data --out-root out --include-current
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom import-statement --data-dir data --out-root out --plugin csv-generic --input data-sample/sample_statement.csv --write
uv run rikdom storage-sync --data-dir data --out-root out --plugin duckdb-storage --plugins-dir plugins
uv run rikdom migrate --portfolio data-sample/portfolio.json --dry-run
uv run ruff check .
uv run python -m unittest tests.test_cli_reconcile -v
```

See `docs/how-to/author-a-migration.md` and `docs/how-to/back-up-before-migration.md` for the migration authoring guide and backup strategy.
