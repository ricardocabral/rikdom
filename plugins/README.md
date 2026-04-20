# Plugin System Quickstart

This directory contains local plugins loaded by `rikdom`.

Canonical docs:
- [docs/plugin-system.md](../docs/plugin-system.md)

Current plugin examples:
- `csv-generic` and `b3-consolidado-mensal`: legacy command-based `source/input` imports.
- `quarto-portfolio-report`: Pluggy `output` plugin.
- `duckdb-storage`: Pluggy `state/storage` plugin.

## Folder Shape

- `plugins/<plugin-name>/plugin.json` (required)
- `plugins/<plugin-name>/...` plugin code/assets

## Fast Validation Commands

```bash
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom import-statement --plugin csv-generic --input data/sample_statement.csv --portfolio data/portfolio.json
uv run rikdom render-report --plugin quarto-portfolio-report --plugins-dir plugins
uv run rikdom storage-sync --plugin duckdb-storage --plugins-dir plugins
uv run pytest -q tests/test_plugins.py tests/test_output_plugin_pipeline.py tests/test_duckdb_storage_plugin.py tests/test_quarto_report_mapping.py
```

## Safety Baseline

- Treat plugin code as trusted local code: both subprocess and in-process modes can execute arbitrary Python.
- Never commit secrets or credentials inside plugin files.
- Keep plugins deterministic and idempotent for repeatable runs.
