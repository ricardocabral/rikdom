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

## Phase 1 (P0): Canonical Schema + Validation + Migration Basis

**User stories**: durable schema for years, easy evolution, country-specific asset classes

### What to build

Stabilize canonical schema contracts (`portfolio`, `snapshot`, plugin statement), define compatibility policy, and add migration scaffold.

### Acceptance criteria

- [ ] Core schemas document versioning and extension rules.
- [ ] Validation command catches compatibility and integrity issues.
- [ ] Migration conventions are documented for future bumps.

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

- [ ] Writes are atomic (temp+rename or equivalent strategy).
- [ ] Append-only history is documented and test-covered.
- [ ] Backup/restore metadata strategy is documented.
- [ ] DuckDB mirror plugin can sync from canonical JSON transactionally and idempotently.
- [ ] Mirror consistency metadata (`source_hash_portfolio`, `source_hash_snapshots`) is persisted and checked.
- [ ] Backup/checkpoint runbook exists for DuckDB mirror mode.

---

## Phase 3 (P0): Pluggy Import + Asset-Type Catalog Foundation

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

- [x] `import-statement` executes a `source/input` plugin through Pluggy.
- [ ] `asset_type_catalog` can be composed from `asset-type/catalog` plugins before import merge.
- [ ] Import commands capture provenance fields.
- [ ] Duplicate imports are detected deterministically.
- [ ] Import reports expose inserted/updated/skipped counts.
- [x] `csv-generic` is migrated to native Pluggy plugin class.
- [ ] Wave 1 Brazilian asset-type plugins ship with at least `fii`, `tesouro_direto`, `lci`, `lca`, `cri`, and `cra`.
- [ ] Wave 2 Brazilian asset-type plugins ship with `debenture_incentivada`, `debenture_infra`, `bdr`, and `coe`.
- [ ] Wave 3 Brazilian asset-type plugins ship with `fidc_cota` and `fiagro_cota`.
- [ ] Validation enforces Brazil identifier and instrument-attribute conventions for all shipped waves.

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

- [ ] Total value, timeline, and class allocation render offline.
- [ ] Dashboard is usable on desktop and mobile.
- [ ] Output requires no external services.
- [ ] Quarto output plugin renders allocation, timeline, currency split, asset-type, geography, and risk slices from default JSON files.
- [ ] Quarto plugin emits artifact metadata and clear dependency/preflight errors.

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

- [ ] Plugin manifest and API version are enforced at load time.
- [ ] Loader rejects unknown `plugin_types` and invalid module/class targets.
- [ ] SDK template reduces boilerplate for new plugins.
- [ ] CI checks plugin fixtures against schema and hook contracts.
- [ ] Plugin listing command exposes installed plugin metadata.
- [ ] Asset-type plugin packs include compatibility checks against `schema/portfolio.schema.json`.
- [ ] Asset-type plugin packs include contract tests for `cnpj`, `isin`, indexer enums, and type-specific required attributes.
- [ ] Output plugin packs include contract tests for artifact generation and error classes.
- [ ] Storage plugin packs include contract tests for transactional sync, stale-read detection, and health checks.

---

## Phase 6 (P1/P2): Advanced Valuation + Interchange + Analytics

**User stories**: richer analysis and portability ecosystem

### What to build

Add quote/FX history model, export package format with checksums, and extended analytics roadmap.

### Acceptance criteria

- [ ] Quote/FX model supports deterministic valuation snapshots.
- [ ] Export package is self-describing and integrity-checked.
- [ ] Advanced analytics scope is captured in roadmap issues.

---

## Execution Companion

Detailed task-by-task execution plan (TDD steps, file-level edits, commit checkpoints):

- `docs/superpowers/plans/2026-04-20-pluggy-plugin-engine.md`
