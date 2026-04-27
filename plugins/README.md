# Plugin System Quickstart

This directory contains local plugins loaded by `rikdom`.

Canonical docs:
- [docs/plugin-system.md](../docs/plugin-system.md) (see [Authoring a plugin](../docs/plugin-system.md#authoring-a-plugin) for the `rikdom plugin init` walkthrough)
- [docs/plugin-compatibility.md](../docs/plugin-compatibility.md) (semver policy and stability tiers)

Plugin docs:
- [csv-generic](csv-generic/README.md)
- [ghostfolio_export_json](ghostfolio_export_json/README.md)
- [ibkr_flex_xml](ibkr_flex_xml/README.md)
- [portfolio_performance_csv](portfolio_performance_csv/README.md)
- [wealthfolio_export_json](wealthfolio_export_json/README.md)
- [wealthfolio_activity_csv](wealthfolio_activity_csv/README.md)
- [charles-schwab](charles-schwab/README.md)
- [b3-consolidado-mensal](b3-consolidado-mensal/README.md)
- [btg_wm_conta_internacional](btg_wm_conta_internacional/README.md)
- [quarto-portfolio-report](quarto-portfolio-report/README.md)
- [duckdb-storage](duckdb-storage/README.md)
- [asset-types-br-catalog](asset-types-br-catalog/README.md)

## Folder Shape

- `plugins/<plugin-name>/plugin.json` (required)
- `plugins/<plugin-name>/...` plugin code/assets

## Fast Validation Commands

```bash
make plugins-list
uv run pytest -q tests/test_plugins.py tests/test_asset_type_catalog_plugins.py
```

Plugin-specific prerequisites and run commands are documented in each plugin README.
Use tracked sample fixtures (for example `data-sample/portfolio.json` or `tests/fixtures/portfolio.json`) in examples so commands work in a clean checkout.

## Safety Baseline

- Treat plugin code as trusted local code: Pluggy plugins execute arbitrary Python in-process.
- Never commit secrets or credentials inside plugin files.
- Keep plugins deterministic and idempotent for repeatable runs.
