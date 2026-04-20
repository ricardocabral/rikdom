# Schema Design

## Goals

- Long-term portable data model in plain JSON.
- Readable by humans and LLMs.
- Country-aware asset-type extensibility.
- Deterministic imports through event idempotency and provenance.
- Additive evolution over time with low migration burden.

## Core Files

- `schema/portfolio.schema.json`: canonical current-state portfolio model.
- `schema/snapshot.schema.json`: historical aggregate points for progress tracking.
- `schema/plugin-statement.schema.json`: normalized plugin import output.
- `schema/default-asset-types.json`: starter catalog.

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

- `schema_version`
- `schema_uri`

Recommended compatibility rule:

- Readers should support at least the previous two minor versions.
- Writers should emit only the current version.

### 2. Country-Specific Asset Types

Asset types are first-class records in `asset_type_catalog`:

- `id`, `label`, `asset_class`
- `availability.countries`
- optional domain metadata

Holdings only reference `asset_type_id`, so users can add country-specific instrument classes without changing the holding format.

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
