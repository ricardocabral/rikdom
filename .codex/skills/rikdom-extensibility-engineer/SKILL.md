# Skill: Rikdom Extensibility Engineer (Technical)

Use this skill for advanced users extending rikdom: schema evolution, plugin development, plugin engine wiring, import pipelines, and storage/report integrations.

## First Message (Required)

Ask for runtime context first:

`What is your rikdom portfolio data path? You can send: (1) the data directory, (2) a full path to portfolio.json, or (3) workspace root + portfolio name.`

If missing, default to:
- `--data-dir data`
- `--out-root out`
- no `--portfolio-name`

## File And Contract Map

Canonical data:
- `data/portfolio.json`
- `data/snapshots.jsonl`
- `data/fx_rates.jsonl`
- `data/import_log.jsonl`
- `data/portfolio_registry.json` (optional)
- `data/portfolios/<name>/...` (registry mode)

Schemas:
- `schema/portfolio.schema.json`
- `schema/snapshot.schema.json`
- `schema/plugin-statement.schema.json`
- `schema/default-asset-types.json`

Plugin and runtime internals:
- `src/rikdom/cli.py` (CLI command wiring and workspace path resolution)
- `src/rikdom/plugins.py` (portfolio merge / provenance helpers)
- `src/rikdom/plugin_engine/contracts.py` (`PhaseName` taxonomy)
- `src/rikdom/plugin_engine/hookspecs.py` (hook contracts)
- `src/rikdom/plugin_engine/manifest.py`
- `src/rikdom/plugin_engine/loader.py`
- `src/rikdom/plugin_engine/runtime.py`
- `src/rikdom/plugin_engine/pipeline.py`

Docs:
- `docs/schema-design.md`
- `docs/plugin-system.md`
- `plugins/README.md`

## Plugin Runtime Reality (Important)

- All plugins run through Pluggy (`src/rikdom/plugin_engine/*`). There is no
  subprocess-style plugin path.
- Do not assume all plugin taxonomy phases are already wired to CLI subcommands.

## Plugin Management And Invocation

Inspect plugins:

```bash
uv run rikdom plugins list --plugins-dir plugins
```

Invoke import plugin:

```bash
uv run rikdom import-statement --data-dir <data-dir> --out-root <out-root> --plugin <plugin-name> --input <statement-path> --write
```

Invoke output plugin:

```bash
uv run rikdom render-report --data-dir <data-dir> --out-root <out-root> --plugin <plugin-name> --plugins-dir plugins
```

Invoke storage plugin:

```bash
uv run rikdom storage-sync --data-dir <data-dir> --out-root <out-root> --plugin <plugin-name> --plugins-dir plugins
```

## Extensibility Workflow

1. Confirm hook surface and CLI wiring in `src/rikdom/cli.py` + `src/rikdom/plugin_engine/`.
2. Read or define contract in relevant schema file.
3. Add/update plugin manifest `plugins/<name>/plugin.json`.
4. Implement plugin code in `plugins/<name>/plugin.py` (and helpers).
5. Add/update tests in `tests/`.
6. Validate behavior with CLI + tests.
7. Update docs in plugin README and/or `docs/plugin-system.md`.

## Hook Semantics

- `firstresult=True` hooks select one plugin result (`source_input`, `output`, `state_storage_*`).
- Fan-out hooks aggregate multiple plugin results (`asset_type_catalog`, `observability`, `audit_trail`).

## Compatibility And Safety Rules

- Preserve unknown fields under `metadata` and `extensions`.
- Prefer additive schema changes; avoid breaking required-field removals.
- Keep plugins deterministic and idempotent where possible.
- Treat local plugins as trusted code with side effects.
- Never commit secrets into plugin manifests or code.

## Technical Validation Checklist

On a fresh checkout, seed `data/*` from tracked samples first — the validation
and import commands below read `data/portfolio.json` and related files:

```bash
make bootstrap
```

Then run the checklist:

```bash
make validate
make plugins-list
make import-sample
make render-report
make storage-sync
make test
```
