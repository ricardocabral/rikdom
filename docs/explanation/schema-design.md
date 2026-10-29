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

### Optional income planning evidence

The [income plan contract](../reference/income-plan.md) is a separate, optional
document validated by `schema/income-plan.schema.json`, also shipped as a package
resource. Its integer `version: 1` evolves independently of the portfolio's
`schema_version`; supplying a plan does not migrate the portfolio contract.

The same object can live in a user-selected JSON file passed with
`income --income-plan`, or under `portfolio.extensions.rikdom_income_plan`.
An explicit file takes precedence. The income calculation validates the supported plan
version before producing artifacts; the ordinary portfolio schema preserves
extension data without interpreting that separate financial contract.

Announcements, scenario estimates, reviewed payment links and declared cost
evidence are distinct from actual activities and holdings. Plan revision
selection and payment matching derive report results without creating or
rewriting ledger events. Actual corrections still use the correction-aware
portfolio contract described below. See [storage layout](../reference/storage-layout.md)
for the optional file and embedded forms.

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

- Accept the supported legacy 1.x contracts through 1.7.0 and the correction-aware 2.0.0 contract. Legacy migration defaults remain 1.7.0.
- Reject (or warn loudly on) payloads from a different major: a major bump
  signals intentional breakage.
- Preserve unknown fields under `metadata`/`extensions`; structural preservation does not imply support for unknown financial semantics.
- Reject unsupported contract versions before first-party financial calculations.

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

- `activities[]` stores source events (`buy`, `sell`, `dividend`, etc.).
  Ordinary source imports may refresh an event with the same identity.
  Auditable corrections preserve the original event and append a linked
  replacement; correction chains are protected from source-import rewrites.
- `projections` stores derived views such as computed positions/performance.

Financial readers project the effective correction chain before calculating.
See [enter and correct activities](../how-to/enter-and-correct-activities.md)
for the distinction between a source refresh and an immutable correction.
Projections can be recomputed from the effective ledger.

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

### Correction-aware contract 2.0.0

Rikdom 0.2.0 is the first correction-aware application version. Uncorrected 1.x
portfolios remain supported without forced migration. The first successful manual
or normalized-input correction writes `schema_version: "2.0.0"` and its linked
replacement in the same atomic update; previews show the transition without
writing. Existing 1.x schema-migration paths/defaults remain unchanged.

A correction is a complete activity with its own ID/key and
`extensions.rikdom_correction = {version: 1, supersedes_activity_id, reason}`.
The original remains stored. Only the unsuperseded event participates in financial
calculations; cancellation uses a cancelled replacement. A 1.x file containing
correction links is invalid. Unknown correction versions, forks, cycles, missing
references, and colliding immutable identities fail before writing/calculating.

Updated financial readers check portfolio contracts; activity-list APIs validate
and project correction chains. Raw exports retain the ledger/version. A major
stamp cannot retroactively change old code: older or third-party readers that
bypass version validation may double-count corrections. They are unsupported for
corrected data. No automatic downgrade or backward-calculation guarantee is made.

### Neutral core and source interpretation

Core consumes explicit normalized numbers, dates, identities, currencies, coverage,
and policy parameters. Source plugins select locale/timezone conventions, account
mappings, and regional instrument identity rules. Regional catalog definitions and
constants remain with their plugins. A reporting currency is required, and monetary
calculation precision is retained rather than forcing two decimal places for every
currency. Output plugins choose display formatting.

Canonical instrument keys are opaque, source-produced metadata. Stored keys are
preserved; core no longer invents Brazilian/US identities or defaults unknown
markets to the US. Optional canonical collapse also requires an explicit matching
account and unique candidate. Different accounts remain separate positions.
