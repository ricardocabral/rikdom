# Plugin System Quickstart

This directory contains local plugins loaded by `rikdom`.

Canonical docs:
- [docs/plugin-system.md](../docs/plugin-system.md)

Current plugin examples:
- `csv-generic`: legacy command-based `source/input` import.
- `b3-consolidado-mensal`: hybrid `source/input` import (legacy command + Pluggy hook).
- `quarto-portfolio-report`: Pluggy `output` plugin.
- `duckdb-storage`: Pluggy `state/storage` plugin.
- `asset-types-br-catalog`: Pluggy `asset-type/catalog` plugin with Brazilian asset types (`fii`, `tesouro_direto`, `lci`, `lca`, `cri`, `cra`, `debenture_incentivada`, `debenture_infra`, `bdr`, `coe`, `fidc_cota`, `fiagro_cota`).

Plugin readmes:
- [b3-consolidado-mensal/README.md](b3-consolidado-mensal/README.md)
- [quarto-portfolio-report/README.md](quarto-portfolio-report/README.md)
- [duckdb-storage/README.md](duckdb-storage/README.md)
- [asset-types-br-catalog/README.md](asset-types-br-catalog/README.md)

## Folder Shape

- `plugins/<plugin-name>/plugin.json` (required)
- `plugins/<plugin-name>/...` plugin code/assets

## Fast Validation Commands

```bash
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom import-statement --plugin csv-generic --input data/sample_statement.csv --portfolio data/portfolio.json
uv run rikdom import-statement --plugin b3-consolidado-mensal --input /path/to/relatorio-consolidado-mensal.xlsx --portfolio data/portfolio.json
uv run rikdom render-report --plugin quarto-portfolio-report --plugins-dir plugins
uv run rikdom storage-sync --plugin duckdb-storage --plugins-dir plugins
uv run pytest -q tests/test_plugins.py tests/test_output_plugin_pipeline.py tests/test_duckdb_storage_plugin.py tests/test_quarto_report_mapping.py
```

## Prerequisites

Pluggy does not install dependencies by itself. Dependencies must be installed in the Python/runtime environment before running a plugin.

`quarto-portfolio-report`:

```bash
brew install --cask quarto
quarto --version
```

`duckdb-storage`:

```bash
uv add duckdb
uv run python -c "import duckdb; print(duckdb.__version__)"
```

## Safety Baseline

- Treat plugin code as trusted local code: both subprocess and in-process modes can execute arbitrary Python.
- Never commit secrets or credentials inside plugin files.
- Keep plugins deterministic and idempotent for repeatable runs.
