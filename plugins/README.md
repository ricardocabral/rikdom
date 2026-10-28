# Plugin System Quickstart

This directory contains local plugins loaded by `rikdom`.

Canonical docs:
- [Plugin architecture](../docs/explanation/plugin-architecture.md) (lifecycle, taxonomy, dispatch)
- [Query external data](../docs/how-to/query-external-data.md) (discover a connector, query data, inspect results)
- [Author your first plugin](../docs/tutorials/first-plugin.md) (`rikdom plugin init` walkthrough)
- [Plugin manifest reference](../docs/reference/plugin-manifest.md) and [plugin hooks reference](../docs/reference/plugin-hooks.md)
- [Plugin compatibility & stability](../docs/explanation/plugin-compatibility.md) (semver policy and stability tiers)

Plugin docs:
- [brapi](brapi/README.md)
- [csv-generic](csv-generic/README.md)
- [ghostfolio_export_json](ghostfolio_export_json/README.md)
- [ibkr_flex_xml](ibkr_flex_xml/README.md)
- [portfolio_performance_csv](portfolio_performance_csv/README.md)
- [wealthfolio_export_json](wealthfolio_export_json/README.md)
- [wealthfolio_activity_csv](wealthfolio_activity_csv/README.md)
- [charles-schwab](charles-schwab/README.md)
- [b3-consolidado-mensal](b3-consolidado-mensal/README.md)
- [btg_wm_conta_internacional](btg_wm_conta_internacional/README.md)
- [irpf-xml](irpf-xml/README.md)
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

## External Connectors

`external/connector` plugins expose provider operations through Experimental
`connector_describe` and `connector_query` hooks in API `1.1`. Existing API
`1.0` plugins remain unchanged:

```bash
uv run rikdom connector describe --plugin '<connector>' --plugins-dir plugins
uv run rikdom connector query --plugin '<connector>' --operation '<operation>' \
  --params '{}' --plugins-dir plugins
```

Replace the placeholders and parameter object using the selected plugin's
README and description.

Core passes the operation and JSON parameter object to the selected plugin;
the plugin owns provider rules, authentication, and REST or MCP transport.
No concrete MCP transport is included yet.
Responses preserve provider-native JSON and do not import holdings or ledger
events, update canonical files, or replace the FX provider.
The CLI wraps responses under `data` with the selected plugin's identity,
version, operation, and retrieval time. See the
[connector workflow](../docs/how-to/query-external-data.md) for authentication,
result handling, and how another REST or MCP provider fits this boundary.

## Safety Baseline

- Treat plugin code as trusted local code: Pluggy plugins execute arbitrary Python in-process.
- Never commit secrets or credentials inside plugin files.
- Keep plugins deterministic and idempotent for repeatable runs.

## Explicit sources and trust

All first-party source plugins emit history-coverage and unsupported-event
[diagnostics](../docs/reference/import-diagnostics.md). A positions-only importer
cannot establish transaction history. Regional identity and parsing conventions
belong to the source/catalog plugins; core preserves their opaque canonical keys.

[Frankfurter](frankfurter/README.md) is an optional FX connector. Snapshot acquisition
requires `--fx-provider frankfurter`; core diagnostics/report flows remain local.
Manual entry and immutable corrections use the existing
[normalized JSON importer](normalized-statement-json/README.md) and
[correction workflow](../docs/how-to/enter-and-correct-activities.md).
