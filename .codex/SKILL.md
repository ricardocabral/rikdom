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
3. Prefer `make <target>` for routine workflows; use `uv run ...` for targeted debugging and ad-hoc scripts.
4. Validate baseline behavior first:
   - `make bootstrap`
   - `make validate`
   - `make plugins-list`
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

Preferred task runner (mirrors `Makefile`):

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

Direct command equivalents:

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

## Output Expectations

- State assumptions explicitly.
- Mention valuation caveats when FX conversion data is missing.
- Reference touched files and tests run.
