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
- [frankfurter](frankfurter/README.md)
- [local-market-series](local-market-series/README.md) — normalized file/manual price and FX enrichment, experimental API 1.2.
- [csv-generic](csv-generic/README.md)
- [ghostfolio_export_json](ghostfolio_export_json/README.md)
- [ibkr_flex_xml](ibkr_flex_xml/README.md)
- [portfolio_performance_csv](portfolio_performance_csv/README.md)
- [wealthfolio_export_json](wealthfolio_export_json/README.md)
- [wealthfolio_activity_csv](wealthfolio_activity_csv/README.md)
- [charles-schwab](charles-schwab/README.md)
- [b3-consolidado-mensal](b3-consolidado-mensal/README.md)
- [btg_wm_conta_internacional](btg_wm_conta_internacional/README.md)
- [btg-investment-pdf](btg-investment-pdf/README.md)
- [fidelity](fidelity/README.md)
- [vanguard](vanguard/README.md)
- [normalized-statement-json](normalized-statement-json/README.md)
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
uv run python -m unittest tests.test_plugins tests.test_asset_type_catalog_plugins -v
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

## Posted-income coverage by source

The table covers every first-party `source/input` plugin. Provider cash amounts
whose gross/net basis is not established declare `metadata.rikdom_income` version
1 with `amount_basis: unknown`. Missing withholding is unknown; a reported zero
is evidence. Separate tax events are never linked to income by the importer.
Only posted `dividend` and `interest` events enter received-income totals;
generic `income` stays outside those totals.

| Source | Posted-income path and amount basis | Coverage limit |
| --- | --- | --- |
| [b3-consolidado-mensal](b3-consolidado-mensal/README.md) | Movimentação dividends/JCP and generic rendimentos; unknown basis | Position sheets are holdings only. Reversals, tax labels and unsupported directions remain in diagnostics for review. |
| [btg-investment-pdf](btg-investment-pdf/README.md) | No posted-income activities | Positions, receivables, acquisition observations and movement section evidence do not establish received income. |
| [btg_wm_conta_internacional](btg_wm_conta_internacional/README.md) | `DIV` dividend, unknown basis; `DIVNRA` separate signed tax | Unknown activity codes remain `other` with diagnostics. Accrued interest headings and synthetic openings are not received income. |
| [charles-schwab](charles-schwab/README.md) | Dividend/interest amounts have unknown basis; signed tax/refund events stay separate | No automatic linkage of tax rows or complete-history assertion. |
| [csv-generic](csv-generic/README.md) | Caller-normalized canonical activities; gross by canonical default, or explicit gross/net/unknown | Caller must supply event type, currency, basis and charges correctly; no provider label interpretation. |
| [fidelity](fidelity/README.md) | CSV dividends/interest have unknown basis; signed tax/refund events stay separate | Normalized export rows required; no tax linkage or tax-lot reconstruction. |
| [ghostfolio_export_json](ghostfolio_export_json/README.md) | Explicit net/gross aliases establish basis; ambiguous amount/value aliases stay unknown | Attached charges retain their own evidence/currencies; generic income and tax events are separate. |
| [ibkr_flex_xml](ibkr_flex_xml/README.md) | CashTransaction dividends/interest have unknown basis; withholding/refunds stay separate | Cash amount alone does not establish gross/net or tax linkage. |
| [irpf-xml](irpf-xml/README.md) | No posted-income activities | Annual asset declarations and receivables establish holdings only. |
| [normalized-statement-json](normalized-statement-json/README.md) | Canonical passthrough preserves caller's income markers, amounts, charges and metadata | Unmarked canonical amounts follow the schema gross convention; caller establishes source semantics and history. |
| [portfolio_performance_csv](portfolio_performance_csv/README.md) | Transaction Value is net; Gross Amount fallback is gross in its own currency | Missing charges remain unreported; source amounts are not converted between currencies. |
| [vanguard](vanguard/README.md) | CSV and OFX dividends/interest have unknown basis; CSV tax/refund events stay separate | OFX supports DIV/INTEREST; unsupported transaction/income variants remain explicit. |
| [wealthfolio_activity_csv](wealthfolio_activity_csv/README.md) | Explicit amount is net; quantity × price fallback has unknown basis | Generic income is not reclassified as dividends; attached tax/fee evidence is preserved. |
| [wealthfolio_export_json](wealthfolio_export_json/README.md) | Explicit amount/net_amount is net; quantity × price fallback has unknown basis | Generic income is not reclassified as dividends; attached tax/fee evidence is preserved. |

The other first-party plugins (`asset-types-br-catalog`, `brapi`,
`duckdb-storage`, `frankfurter`, `quarto-portfolio-report`) provide catalogs,
external queries, storage or output. They do not import posted source income.
