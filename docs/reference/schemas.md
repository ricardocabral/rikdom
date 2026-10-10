# Schemas Reference

Rikdom ships JSON Schemas for every persisted shape. Schemas are the source
of truth; this page indexes them and summarizes their roles. For the design
rationale, see [schema design](../explanation/schema-design.md).

## Schema files

| File | Role |
| --- | --- |
| `schema/portfolio.schema.json` | Canonical current-state portfolio model. Reproducible fixture: `data-sample/portfolio.json`. Core sections: `profile`, `settings`, `asset_type_catalog`, `holdings`. Optional ledgers: `activities`, `operations`, `liabilities`, `tax_lots`. |
| `schema/snapshot.schema.json` | One historical snapshot record. Reproducible fixture: `data-sample/snapshots.jsonl`. Required: `timestamp`, `base_currency`, aggregated totals. |
| `schema/plugin-statement.schema.json` | Normalized provider/plugin import payload contract before merge into canonical state. |
| `schema/default-asset-types.json` | Starter catalog of asset-type definitions (e.g. `stock`, `reit`, `fund`) mapped to top-level `asset_class` values. |
| `src/rikdom/_resources/policy.schema.json` | Investment Policy Statement (IPS) schema. Bundled as a package resource. |
| `src/rikdom/_resources/plugin.manifest.schema.json` | Plugin manifest contract. See [plugin manifest reference](plugin-manifest.md). |

## Quick term guide

- `asset_type_catalog`: array of allowed asset type definitions in a
  portfolio (unique by `id`).
- `asset_type_id`: reference from each holding to one entry in
  `asset_type_catalog`.
- `asset_class`: top-level reporting group (e.g. `stocks`, `funds`,
  `real_estate`).
- `activities`: immutable event ledger for financial events (`buy`, `sell`,
  `dividend`, `fee`, etc.).
- `operations`: optional recurring operational task definitions plus
  immutable task event history.

## Schema versions

For the version history of each schema track, see
[migration version history](migrations.md).

## See also

- [Schema design](../explanation/schema-design.md) — modeling rationale.
- [Storage layout](storage-layout.md) — where each schema's instances live.
- [Migration version history](migrations.md)

## Reported statement observations (portfolio 1.7)

`statement_observations[]` preserves provider reports separately from current
holdings. Each record has an identity, provider, report period, and a source
path, SHA-256 digest and page count. Optional balances retain their own reference
dates and gross/net values. Sections preserve page numbers, extracted table text,
and normalized rows with provider-specific columns. This supports historical
reconciliation without replacing a current valuation with an older statement.
A plugin may emit only statement observations, with its usual provider and
`generated_at` envelope. Provider account identifiers are strings, not policy
account references.

Holdings may carry `valuation` with current unit price, net value, named tax
provisions, and price reference time. `market_value` continues to hold gross
value; estimated provisions are distinct from posted withholding activities.
Optional `acquisition_observations[]` stores dated broker lot observations with
remaining quantity, purchase unit price, reported purchase amount and valuation.
`cost_basis_kind` distinguishes reported purchase values, broker adjusted
purchase values, and unknown semantics. An adjusted amount is not automatically
a tax-lot cost basis, and these observations do not create transactions.

Fixed-income coupon terms optionally preserve `indexer_multiplier_pct` (102.25
means 102.25% of the index), `reported_rate`, and `rate_scope` (`purchase` or
`weighted_average`). An index multiplier differs from an additive spread.
Existing snapshots remain aggregate records; statement observations retain the
source tables and historical positions instead of duplicating the holding model
inside snapshots. All new fields are optional for older portfolio files.
