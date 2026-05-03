# Schema Design

This page explains *why* the rikdom schema is shaped the way it is and the
evolution rules that keep portfolios readable for years. For the field-level
contracts, see [schemas reference](../reference/schemas.md). For migration
mechanics, see [run a migration](../how-to/run-a-migration.md) and
[migration version history](../reference/migrations.md).

## Goals

- Long-term portable data model in plain JSON.
- Readable by humans and LLMs.
- Country-aware asset-type extensibility.
- Deterministic imports through event idempotency and provenance.
- Additive evolution over time with low migration burden.

## Modeling strategy

### 1. Stable core + extension slots

`portfolio.json` has a strict core:

- `profile`
- `settings`
- `asset_type_catalog`
- `holdings`

Extensibility slots:

- `extensions` at portfolio and holding levels
- `metadata` at asset-type and holding levels

This keeps baseline interoperability while allowing local customization
without forks.

### 1.1 Contract identity

Top-level schema contract fields:

- `schema_version` — semantic version `MAJOR.MINOR.PATCH`.
- `schema_uri` — canonical URI of the portfolio contract. Currently
  `https://example.org/rikdom/schema/portfolio.schema.json`.

### 1.2 Compatibility policy

Rikdom follows a deliberate semver-based compatibility contract so
long-lived portfolios stay readable across years of tooling evolution.

**Writer obligations**

- Emit the current `schema_version` (see `CURRENT_SCHEMA_VERSION` in
  `src/rikdom/validate.py`).
- Emit the canonical `schema_uri`.
- Never remove required fields from a stored portfolio. Prefer additive
  evolution.
- Preserve unknown `metadata`/`extensions` on round-trips
  (read-modify-write must not drop them).

**Reader obligations**

- Accept any `schema_version` within the current major, down to
  `MIN_COMPATIBLE_SCHEMA_VERSION`.
- Reject (or warn loudly on) payloads from a different major: a major bump
  signals intentional breakage.
- Tolerate unknown top-level or nested fields under `metadata`/`extensions`:
  forward-compatible readers must not error on newer minor versions.
- Warn when encountering a `schema_version` newer than `CURRENT_SCHEMA_VERSION`.

**Version-bump rules**

- PATCH: doc-only, clarifications, or validator-only improvements. No shape change.
- MINOR: additive fields, new optional enums, new optional top-level sections.
- MAJOR: removals, renames, required-field changes, or breaking semantic shifts.

### 2. Country-specific asset types

Asset types are first-class records in `asset_type_catalog`:

- `id`, `label`, `asset_class`
- `availability.countries`
- optional domain metadata
- optional `instrument_attributes[]` for per-type attribute definitions

Holdings only reference `asset_type_id`, so users can add country-specific
instrument classes without changing the holding format. This keeps the core
holding shape minimal while pushing variation into a typed catalog.

For instrument-specific fields, define a typed contract in
`asset_type_catalog[].instrument_attributes` and store values in
`holdings[].instrument_attributes` keyed by attribute `id`.

Example for Brazilian sovereign bonds:

- `index` (`string`, required)
- `expiration_year` (`integer`, required)
- `semestral_payments` (`boolean`, required)

### 3. Currency handling

Each holding carries `market_value.amount` + `currency`. When non-base
currency values are present, the snapshot-time FX lock provides
deterministic aggregation — see
[multi-currency engine](multi-currency-engine.md).

### 4. Time dimension

- Current state fixture: `data-sample/portfolio.json` (often copied to
  local `data/portfolio.json`).
- Historical trend fixture: `data-sample/snapshots.jsonl` (often copied to
  local `data/snapshots.jsonl`).

Snapshots avoid rewriting full history and remain append-only.

### 5. Event ledger + projections

- `activities[]` stores immutable events (`buy`, `sell`, `dividend`, etc.).
- `projections` stores derived views such as computed positions/performance.

This separation keeps imported truth stable while allowing analytics to
evolve. The ledger is the source of truth; projections can be recomputed.

### 6. Recurring operational tasks

Wealth and portfolio management usually include recurring non-trade
operations (monthly, quarterly, yearly):

- `operations.task_catalog[]`: task definitions and cadence rules.
- `operations.task_catalog[].cadence.frequency`: `monthly`, `quarterly`,
  `yearly`, or `custom`.
- `operations.task_catalog[].last_completed_at`: direct "last done" pointer.
- `operations.task_catalog[].last_event_id`: optional reference to the
  ledger occurrence that closed the task.
- `operations.task_events[]`: immutable occurrences with required `occurred_at`.

The recommended pattern is to update `last_completed_at` and append a new
`task_events[]` entry whenever a recurring task is completed or skipped.

### 7. Import provenance and idempotency

Both holdings and activities can include provenance fields:

- `source_system`
- `source_ref`
- `import_run_id`
- `idempotency_key`
- `ingested_at`

These fields reduce duplicate imports and make reconciliation auditable.

## Evolution rules

1. Prefer additive fields over renames/removals.
2. Bump `schema_version` on model changes — see
   [migration version history](../reference/migrations.md).
3. Preserve unknown `metadata`/`extensions` during transforms.
4. If a breaking change is unavoidable, ship a migration and a converter
   script — see [author a new migration](../how-to/author-a-migration.md).

## See also

- [Schemas reference](../reference/schemas.md)
- [Migration version history](../reference/migrations.md)
- [Calculation trust](calculation-trust.md)
