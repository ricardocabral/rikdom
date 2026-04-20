# Schema Design

## Goals

- Long-term portable data model in plain JSON.
- Readable by humans and LLMs.
- Country-aware asset-type extensibility.
- Deterministic imports through event idempotency and provenance.
- Additive evolution over time with low migration burden.

## Core Files

- `schema/portfolio.schema.json`: canonical current-state portfolio model (`data/portfolio.json`) with core sections (`profile`, `settings`, `asset_type_catalog`, `holdings`) and optional ledgers (`activities`, `operations`).
- `schema/snapshot.schema.json`: one historical snapshot record from `data/snapshots.jsonl` with `timestamp`, `base_currency`, and aggregated totals.
- `schema/plugin-statement.schema.json`: normalized provider/plugin import payload contract before merge into canonical portfolio state.
- `schema/default-asset-types.json`: starter catalog of asset-type definitions (for example `stock`, `reit`, `fund`) mapped to top-level `asset_class` values.

## Quick Term Guide

- `asset_type_catalog`: dictionary of allowed asset types in a portfolio.
- `asset_type_id`: reference from each holding to one entry in `asset_type_catalog`.
- `asset_class`: top-level reporting group (for example `stocks`, `funds`, `real_estate`).
- `activities`: immutable event ledger for financial events (`buy`, `sell`, `dividend`, `fee`, etc.).
- `operations`: optional recurring operational task definitions plus immutable task event history.

## Modeling Strategy

### 1. Stable Core + Extension Slots

`portfolio.json` has a strict core:

- `profile`
- `settings`
- `asset_type_catalog`
- `holdings`

Extensibility slots:

- `extensions` at portfolio and holding levels
- `metadata` at asset-type and holding levels

This keeps baseline interoperability while allowing local customization.

### 1.1 Contract Identity

Top-level schema contract fields:

- `schema_version` — semantic version `MAJOR.MINOR.PATCH`.
- `schema_uri` — canonical URI of the portfolio contract. Currently `https://example.org/rikdom/schema/portfolio.schema.json`.

### 1.2 Compatibility Policy

Rikdom follows a deliberate semver-based compatibility contract so long-lived portfolios stay readable across years of tooling evolution.

**Writer obligations**

- Emit the current `schema_version` (see `CURRENT_SCHEMA_VERSION` in `src/rikdom/validate.py`).
- Emit the canonical `schema_uri`.
- Never remove required fields from a stored portfolio. Prefer additive evolution.
- Preserve unknown `metadata`/`extensions` on round-trips (read-modify-write must not drop them).

**Reader obligations**

- Accept any `schema_version` within the current major, down to `MIN_COMPATIBLE_SCHEMA_VERSION`.
- Reject (or warn loudly on) payloads from a different major: a major bump signals intentional breakage.
- Tolerate unknown top-level or nested fields under `metadata`/`extensions`: forward-compatible readers must not error on newer minor versions.
- Warn when encountering a `schema_version` newer than `CURRENT_SCHEMA_VERSION` — structure may be parseable but semantics of new fields are not guaranteed.

**Version-bump rules**

- PATCH: doc-only, clarifications, or validator-only improvements. No shape change.
- MINOR: additive fields, new optional enums, new optional top-level sections. Old readers must keep working.
- MAJOR: removals, renames, required-field changes, or breaking semantic shifts. Ship a migration note and a converter script.

**Validator behavior**

`rikdom validate` reports compatibility mismatches as errors:

- Non-semver `schema_version` strings.
- Major mismatch between payload and reader.
- `schema_version` below `MIN_COMPATIBLE_SCHEMA_VERSION`.
- `schema_version` newer than `CURRENT_SCHEMA_VERSION` (future payload).
- `schema_uri` not matching the canonical URI.

### 2. Country-Specific Asset Types

Asset types are first-class records in `asset_type_catalog`:

- `id`, `label`, `asset_class`
- `availability.countries`
- optional domain metadata
- optional `instrument_attributes[]` for per-type attribute definitions

Holdings only reference `asset_type_id`, so users can add country-specific instrument classes without changing the holding format.

For instrument-specific fields, define a typed contract in `asset_type_catalog[].instrument_attributes` and store values in `holdings[].instrument_attributes` keyed by attribute `id`.

Example for Brazilian sovereign bonds:

- `index` (`string`, required)
- `expiration_year` (`integer`, required)
- `semestral_payments` (`boolean`, required)

### 3. Currency Handling

Each holding carries `market_value.amount` + `currency`.
When non-base-currency values are present, optional `metadata.fx_rate_to_base` enables deterministic local aggregation.

### 4. Time Dimension

- Current state: `data/portfolio.json`
- Historical trend: `data/snapshots.jsonl`

Snapshots avoid rewriting full history and remain append-only.

### 5. Event Ledger + Projections

- `activities[]` stores immutable events (`buy`, `sell`, `dividend`, etc.).
- `projections` stores derived views such as computed positions/performance.

This separation keeps imported truth stable while allowing analytics to evolve.

### 6. Recurring Operational Tasks

Wealth and portfolio management usually include recurring non-trade operations (monthly, quarterly, yearly).

- `operations.task_catalog[]`: task definitions and cadence rules.
- `operations.task_catalog[].cadence.frequency`: `monthly`, `quarterly`, `yearly`, or `custom`.
- `operations.task_catalog[].last_completed_at`: direct "last done" pointer for fast reads.
- `operations.task_catalog[].last_event_id`: optional reference to the exact ledger occurrence that most recently closed the task.
- `operations.task_events[]`: immutable occurrences with required `occurred_at`.

Typical tasks:

- monthly rebalance review
- monthly cash sweep
- annual tax package reconciliation
- yearly policy/compliance review

The recommended pattern is to update `last_completed_at` and append a new `task_events[]` entry whenever a recurring task is completed or skipped.

### 7. Import Provenance And Idempotency

Both holdings and activities can include provenance fields:

- `source_system`
- `source_ref`
- `import_run_id`
- `idempotency_key`
- `ingested_at`

These fields reduce duplicate imports and make reconciliation auditable.

## Evolution Rules

1. Prefer additive fields over renames/removals.
2. Bump `schema_version` on model changes.
3. Preserve unknown `metadata`/`extensions` during transforms.
4. If a breaking change is unavoidable, document migration steps and keep converter scripts.
