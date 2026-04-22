# Plan: rikdom v0.1-v0.3

> Source PRD: initial user brief in Codex thread (2026-04-20)  
> Cohesion update: Pluggy-first plugin engine integration merged on 2026-04-20.

## Architectural decisions

Durable decisions applied across phases:

- **Storage**: local `JSON` (`portfolio.json`) + append-only `JSONL` snapshots.
- **Schema contract**: JSON Schema 2020-12 + explicit `schema_uri` and semantic `schema_version`.
- **Data model**: immutable `activities` ledger + derived `projections`.
- **Plugin runtime**: in-process Python plugin engine using `pluggy` (no subprocess command contract as primary path).
- **Plugin taxonomy**: lifecycle (`source/input`, `transform`, `enrichment`, `strategy/decision`, `execution`, `output`), domain (`asset-type/catalog`), plus cross-cutting (`risk/compliance`, `state/storage`, `orchestration`, `observability`, `auth/security`, `notification`, `simulation/backtest`).
- **Plugin manifest**: `plugins/<name>/plugin.json` with `name`, `version`, `api_version`, `plugin_types`, `module`, `class_name`.
- **Import boundary**: `source/input` plugins must return normalized statement JSON with provenance-ready fields.
- **Asset-type boundary**: `asset-type/catalog` plugins return typed asset definitions to compose `asset_type_catalog` before import/validation.
- **Output boundary**: `output` plugins can render portfolio reports; Quarto-based rendering is the prioritized pluginized path.
- **Storage boundary**: `state/storage` plugins can maintain optional query mirrors (DuckDB) while canonical truth remains JSON files.
- **Idempotency**: imported objects carry `idempotency_key` and `import_run_id`.
- **Visualization**: static offline HTML generated from local files.

---

## Adoption-first Priority Stack (Updated 2026-04-21)

Highest-impact initiatives are now explicitly prioritized for adoption and retention:

1. **P0**: Calculation trust layer (deterministic, explainable numbers and reconciliations).
2. **P0**: First-party importer reliability (`ghostfolio`, `ibkr`, `portfolio-performance`, `wealthfolio`) with row-level errors and dry-run diff.
3. **P0**: Native multi-currency valuation engine with deterministic FX context.
4. **P0**: Dividend/income automation and monthly/yearly income views.
5. **P0**: Multi-portfolio workspace model (real, paper, retirement, etc.).
6. **P0/P1**: Beginner self-hosted onboarding (one-command bootstrap and guided import path).
7. **P1**: No-surprises data-quality guardrails (drift, missing FX, inconsistent amounts).
8. **P1**: Scheduled auto-refresh snapshots and end-of-day ingest runs.
9. **P1**: Paper/experimental portfolios and strategy clusters.
10. **P2**: AI decision/plugin layer after trust + import + valuation foundations are stable.

Sequencing override:

- Quote/FX history and valuation determinism previously scoped late are pulled forward into P0/P1 execution.

---

## Phase 1 (P0): Canonical Schema + Validation + Migration Basis

**User stories**: durable schema for years, easy evolution, country-specific asset classes

### What to build

Stabilize canonical schema contracts (`portfolio`, `snapshot`, plugin statement), define compatibility policy, and add migration scaffold.

### Acceptance criteria

- [ ] Document core schema versioning and extension rules.
- [ ] Document migration conventions for future schema/version bumps.
- [ ] Ensure the validation command catches compatibility and integrity issues.

---

## Phase 2 (P0): Durable Local Storage Engine

**User stories**: resilient local persistence against tool/runtime changes

### What to build

Implement atomic write strategy, append journal patterns, and periodic snapshot compaction conventions for long-lived local storage.

Storage plugin extension (DuckDB mirror):

- Define `state/storage` plugin contract for sync/query/health:
  - `state_storage_sync(ctx, portfolio_path, snapshots_path, options)`
  - `state_storage_query(ctx, query_name, params)`
  - `state_storage_health(ctx)`
- Implement DuckDB as optional mirror/query engine (not source-of-truth).
- Add mirror consistency contract with source hashes and stale-read policy.

### Acceptance criteria

- [ ] Ensure writes are atomic (temp+rename or equivalent strategy).
- [ ] Document and test-cover append-only history behavior.
- [ ] Document backup/restore metadata strategy.
- [ ] Ensure the DuckDB mirror plugin syncs from canonical JSON transactionally and idempotently.
- [ ] Persist and validate mirror consistency metadata (`source_hash_portfolio`, `source_hash_snapshots`).
- [ ] Publish a backup/checkpoint runbook for DuckDB mirror mode.

---

## Phase 3 (P0): Pluggy Import + Import Reliability + Asset-Type Catalog Foundation

**User stories**: safe recurring imports from providers into local files, plus country-aware asset-type extensibility through plugins

### What to build

Ship the first production slice of the new plugin engine focused on statement imports and asset-type catalog composition:

- Add `src/rikdom/plugin_engine/` with:
  - typed contracts (`contracts.py`)
  - hook specs (`hookspecs.py`)
  - manifest model/validation (`manifest.py`)
  - filesystem discovery (`loader.py`)
  - pluggy runtime + phase runner (`runtime.py`, `pipeline.py`)
- Add an `asset_type_catalog(ctx)` hook and catalog merger that:
  - loads all `asset-type/catalog` plugins
  - merges plugin-provided asset types with deterministic conflict rules
  - validates references from imported holdings to available `asset_type_id`
- Update CLI `import-statement` to call `run_import_pipeline(args.plugin, args.plugins_dir, args.input)`.
- Add CLI command to inspect catalog plugins and effective asset types.
- Keep merge behavior (`inserted/updated`) deterministic.
- Emit import run metadata suitable for audit/idempotency.
- Ship first-party importers targeting migration from widely used tools:
  - `ghostfolio_export_json`
  - `ibkr_flex_xml`
  - `portfolio_performance_csv`
  - `wealthfolio_export_json` (+ `wealthfolio_activity_csv` fallback)
- Add importer preflight and UX contracts:
  - row-level validation report (`rows[]`, `issues[]`, severity, blocking flag)
  - dry-run diff output (`create/update/noop`, field-level `changes[]`, summary counts)
  - canonical issue codes (for example `DATE_PARSE_FAILED`, `INVALID_CURRENCY`, `DUPLICATE_EXISTING`)
- Seed first country catalog plugins for Brazil:
  - Core sovereign/real-estate: `fii`, `tesouro_direto`
  - Bank credit letters: `lci`, `lca`
  - Securitized receivables: `cri`, `cra`
  - Incentivized infra debt: `debenture_incentivada`, `debenture_infra`
  - Market wrapper: `bdr`
  - Structured note: `coe`

### Brazilian Asset-Type Plugin Rollout (researched)

Wave plan for `asset-type/catalog` plugins in Brazil:

- **Wave 1 (P0 MVP)**:
  - `fii`
  - `tesouro_direto`
  - `lci`, `lca`
  - `cri`, `cra`
- **Wave 2 (P1)**:
  - `debenture_incentivada`
  - `debenture_infra`
  - `bdr`
  - `coe`
- **Wave 3 (P1/P2 advanced funds)**:
  - `fidc_cota`
  - `fiagro_cota`

Data-model standards across all Brazil-specific types:

- **Identifiers**:
  - `issuer_cnpj` or `fund_cnpj` or `securitizadora_cnpj` as `^\d{14}$`
  - optional `isin` with Brazil format (`^BR[A-Z0-9]{9}\d$`)
  - optional `b3_ticker` for exchange-traded wrappers
- **Yield/indexing**:
  - `remuneration_type` (`PREFIXADO|POS|HIBRIDO`) where applicable
  - `indexer` (`CDI_DI_OVER|IPCA|SELIC|PREFIXADO`)
  - optional `spread_bps` or `spread_pct`
- **Lifecycle fields**:
  - `issue_date`, `maturity_date`
  - optional `amortization_schedule`, `interest_schedule`
- **Tax profile**:
  - `tax_profile.ir_pf_treatment` (`ISENTO|REGRESSIVO|ALIQUOTA_FIXA|OUTRO`)
  - optional `tax_profile.source_rule_ref`
- **Type-specific attributes**:
  - `tesouro_direto`: `index`, `expiration_year`, optional `semestral_payments`
  - `bdr`: `bdr_level`, `depositary_cnpj`, `underlying_identifier`, `parity_ratio`
  - `coe`: `modalidade`, `underlying_reference`, `payoff_formula`
  - `fidc_cota`: `class_id`, `subclass_type`, `open_closed`
  - `fiagro_cota`: `class_id`, `target_chain`, `fiagro_strategy`

Research basis (official references):

- B3 product pages: LCI, LCA, CRI, CRA, BDR, COE, ISIN, DI methodology.
- CVM regulations: Resoluções 175 (and annexes), 182, 60, and 240.
- Banco Central: Selic reference and CMN Resolução 5.166/2024.
- Receita Federal: CNPJ and Imposto de Renda treatment references.
- ANBIMA: debêntures incentivadas/infra market references.

### Acceptance criteria

- [ ] Compose `asset_type_catalog` from `asset-type/catalog` plugins before import merge.
- [ ] Capture provenance fields in import commands.
- [ ] Detect duplicate imports deterministically.
- [ ] Emit inserted/updated/skipped counts in import reports.
- [ ] Emit row-level error report payloads for all importers in dry-run and apply modes.
- [ ] Emit dry-run diff payloads before write with `create/update/noop` operation summaries.
- [ ] Ship first-party `ghostfolio_export_json` importer with fixtures and mapping tests.
- [ ] Ship first-party `ibkr_flex_xml` importer with cancellation/corporate-action edge-case tests.
- [ ] Ship first-party `portfolio_performance_csv` importer with locale/date/number parsing tests.
- [ ] Ship first-party `wealthfolio_export_json` importer with enum mapping and fallback tests.
- [ ] Ship Wave 1 Brazilian asset-type plugins with at least `fii`, `tesouro_direto`, `lci`, `lca`, `cri`, and `cra`.
- [ ] Ship Wave 2 Brazilian asset-type plugins with `debenture_incentivada`, `debenture_infra`, `bdr`, and `coe`.
- [ ] Ship Wave 3 Brazilian asset-type plugins with `fidc_cota` and `fiagro_cota`.
- [ ] Enforce Brazil identifier and instrument-attribute conventions for all shipped waves during validation.

---

## Phase 3A (P0): Calculation Trust + Multi-Currency Valuation

**User stories**: "numbers must be correct", reproducible FX handling, explainability for portfolio totals and changes

### What to build

- Deterministic valuation layer with explicit quote/FX provenance per calculation period.
- Reconciliation views/contracts:
  - per-holding explainability ("how this value was derived")
  - activity-to-holding consistency checks
  - cross-currency consistency checks (`money.currency`, FX source, FX timestamp).
- Deterministic FX policy:
  - allow locked FX per snapshot run
  - explicit fallback policies and warnings when FX is missing.
- Promote hard-fail validation mode for critical valuation integrity issues.

### Acceptance criteria

- [ ] Make each computed holding value traceable to source amount + FX + timestamp.
- [ ] Ensure portfolio totals are reproducible given the same inputs and FX dataset.
- [ ] Fail strict-mode validation on missing/invalid FX.
- [ ] Ensure reconciliation reports flag amount/quantity inconsistencies with actionable diagnostics.

---

## Phase 4 (P0): Minimal Visualization

**User stories**: allocation overview and progress over time

### What to build

Generate static dashboard from snapshots and current portfolio projections.

Output plugin extension (Quarto reports):

- Add `output` plugin pipeline invocation path (`run_output_pipeline(plugin_name, plugins_dir, portfolio_path, snapshots_path, output_dir)`).
- Implement Quarto plugin to render graphical portfolio report from default `data/` files.
- Keep current built-in HTML dashboard as fallback path until Quarto plugin reaches parity.

### Acceptance criteria

- [ ] Ensure output requires no external services.
- [ ] Render total value, timeline, and class allocation offline.
- [ ] Ensure the dashboard is usable on desktop and mobile.
- [ ] Render allocation, timeline, currency split, asset-type, geography, and risk slices via the Quarto output plugin from default JSON files.
- [ ] Emit artifact metadata and clear dependency/preflight errors from the Quarto plugin.

---

## Phase 4A (P0/P1): Dividend/Income, Multi-Portfolio, and Onboarding

**User stories**: dividend automation, multiple portfolios, easy self-hosted start

### What to build

- Dividend/income automation:
  - normalize dividend/interest/cashflow activities
  - monthly/yearly income summaries and report slices.
- Multi-portfolio workspace:
  - first-class portfolio registry (`main`, `paper`, `retirement`, etc.)
  - isolated imports/reports + optional consolidated rollups.
- Beginner onboarding:
  - one-command bootstrap for self-hosted setup
  - guided import checklist for first successful migration.

### Acceptance criteria

- [ ] Support managing multiple portfolios in one workspace without path-level hacks.
- [ ] Provide a test-covered consolidated view across selected portfolios.
- [ ] Roll up dividend and interest events into monthly/yearly income views.
- [ ] Enable new users to run bootstrap + first import using a documented happy path in under 15 minutes.

---

## Phase 5 (P1): Full Plugin API + SDK + Contract Tests

**User stories**: community-contributed adapters across the full pipeline and shared asset-type packs

### What to build

Expand from import-only foundation to full lifecycle/cross-cutting engine:

- Complete hook coverage for all lifecycle plugin types.
- Stabilize `asset-type/catalog` plugin contract, including schema for instrument attributes.
- Add contract profiles for Brazil-specific types (`credit`, `securitized`, `debt_infra`, `receipt`, `structured_note`, `fund_special`).
- Stabilize typed output payload contract for `output` plugins.
- Stabilize typed `state/storage` contracts for sync/query/health.
- Require and enforce cross-cutting hooks (`risk/compliance`, `observability`, `audit`).
- Add CLI plugin introspection (`rikdom plugins list --plugins-dir plugins`).
- Add SDK scaffolding/templates for new plugins.
- Add fixture-based contract tests for manifests, hook behavior, output schema, and asset-type catalog packs.

### Acceptance criteria

- [ ] Enforce plugin manifest and API version checks at load time.
- [ ] Reject unknown `plugin_types` and invalid module/class targets in the loader.
- [ ] Emit installed plugin metadata through the plugin listing command.
- [ ] Reduce boilerplate for new plugins via SDK templates.
- [ ] Include compatibility checks against `schema/portfolio.schema.json` in asset-type plugin packs.
- [ ] Include contract tests for `cnpj`, `isin`, indexer enums, and type-specific required attributes in asset-type plugin packs.
- [ ] Include contract tests for artifact generation and error classes in output plugin packs.
- [ ] Include contract tests for transactional sync, stale-read detection, and health checks in storage plugin packs.
- [ ] Check plugin fixtures against schema and hook contracts in CI.

---

## Phase 5A (P1): Data Quality Guardrails + Auto-Refresh + Paper Portfolios

**User stories**: no-surprises operation, low-friction recurring updates, safe experimentation

### What to build

- Data quality guardrails:
  - drift detection between activities and holdings
  - strict duplicate detection controls
  - policy-driven warnings vs blocking failures.
- Scheduled refresh:
  - recurring snapshot/import orchestration for end-of-day updates.
- Paper/experimental portfolios:
  - strategy sandbox support with clear isolation from real holdings.

### Acceptance criteria

- [ ] Run guardrail checks consistently and surface machine-readable issue codes.
- [ ] Allow scheduled runs to append snapshots and emit import/validation diagnostics.
- [ ] Isolate paper portfolios and exclude them from real portfolio totals by default.

---

## Phase 6 (P2): Interchange + Advanced Analytics + AI Plugin Layer

**User stories**: richer analysis and portability ecosystem

### What to build

- Expand export/interchange package format with checksums and replay metadata.
- Deliver advanced analytics scope beyond core trust and valuation baseline.
- Introduce AI strategy/decision plugins only after P0/P1 trust and import foundations are stable.

### Acceptance criteria

- [ ] Deliver a self-describing, integrity-checked export package.
- [ ] Capture advanced analytics scope in roadmap issues.
- [ ] Define AI plugin interfaces with guardrails/audit requirements before general enablement.

---

## Execution Companion

Detailed task-by-task execution plan (TDD steps, file-level edits, commit checkpoints):

- `docs/superpowers/plans/2026-04-20-pluggy-plugin-engine.md`
