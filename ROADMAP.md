# Plan: rikdom v0.1-v0.3

## Architectural context

Durable decisions applied across phases:

- **Storage**: local `JSON` (`portfolio.json`) + append-only `JSONL` snapshots.
- **Schema contract**: JSON Schema 2020-12 + explicit `schema_uri` and semantic `schema_version`.
- **Data model**: immutable `activities` ledger + derived `projections`.
- **Plugin runtime**: in-process Python plugin engine using `pluggy`.
- **Plugin taxonomy**: lifecycle (`source/input`, `transform`, `enrichment`, `strategy/decision`, `execution`, `output`), domain (`asset-type/catalog`), plus cross-cutting (`risk/compliance`, `state/storage`, `orchestration`, `observability`, `auth/security`, `notification`, `simulation/backtest`).
- **Plugin manifest**: `plugins/<name>/plugin.json` with `name`, `version`, `api_version`, `plugin_types`, `module`, `class_name`.
- **Import boundary**: `source/input` plugins return normalized statement JSON with provenance-ready fields.
- **Asset-type boundary**: `asset-type/catalog` plugins return typed asset definitions to compose `asset_type_catalog` before import/validation.
- **Output boundary**: `output` plugins can render portfolio reports; Quarto-based rendering is the prioritized pluginized path.
- **Storage boundary**: `state/storage` plugins can maintain optional query mirrors while canonical truth remains JSON files.
- **Idempotency**: imported objects carry `idempotency_key` and `import_run_id`.
- **Visualization**: static offline HTML generated from local files.

---

## Adoption-first Priority Stack

1. **P0**: Complete first-party importer coverage for migrations from Portfolio Performance and Wealthfolio.
2. **P0**: Finish calculation trust UX: per-holding explanations and reconciliation reports that make every total auditable.
3. **P0/P1**: Dividend/income automation with monthly/yearly income views.
4. **P1**: Scheduled auto-refresh snapshots and end-of-day ingest runs.
5. **P1**: Hardening for guided beginner onboarding and first-import migration path.
6. **P1**: Full lifecycle/cross-cutting plugin coverage beyond the currently shipped import/catalog/output/storage hooks.
7. **P2**: Interchange package, advanced analytics, and AI decision/plugin layer after trust + import + valuation foundations are stable.

Sequencing override:

- Complete trust/import/income foundations before expanding AI or advanced strategy plugins.

---

## Phase 3 remainder (P0): Importer Coverage + Import Reliability Hardening

**User stories**: safe recurring imports from common portfolio tools into local files.

### What to build

- Ship remaining first-party importers targeting migration from widely used tools:
  - `portfolio_performance_csv`
  - `wealthfolio_export_json`
  - `wealthfolio_activity_csv` fallback
- Expand importer edge-case fixtures where coverage is still thin:
  - IBKR cancellations and corporate actions.
  - Portfolio Performance locale/date/number parsing.
  - Wealthfolio enum mapping and fallback behavior.

### Acceptance criteria

- [x] Ship first-party `portfolio_performance_csv` importer with locale/date/number parsing tests.
- [x] Ship first-party `wealthfolio_export_json` importer with enum mapping and fallback tests.
- [x] Ship `wealthfolio_activity_csv` fallback importer path with fixtures.
- [x] Add IBKR cancellation/corporate-action edge-case tests.

---

## Phase 3A remainder (P0): Calculation Trust UX + Reconciliation Reports

**User stories**: "numbers must be correct", reproducible valuation, explainability for portfolio totals and changes.

### What to build

- Per-holding explainability views/contracts that show how each value was derived from source amount, FX context, and timestamp.
- Activity-to-holding reconciliation reports.
- Cross-currency reconciliation reports that surface actionable diagnostics for amount/quantity/FX inconsistencies.
- Human-readable and machine-readable report formats suitable for CI and UI consumption.

### Acceptance criteria

- [ ] Make each computed holding value traceable to source amount + FX + timestamp in an exported report.
- [ ] Ensure reconciliation reports flag amount/quantity inconsistencies with actionable diagnostics.
- [ ] Provide stable issue codes for reconciliation findings.
- [ ] Document how to reproduce a portfolio total from raw holdings, activities, and FX history.

---

## Phase 4 remainder (P0/P1): Visualization Hardening

**User stories**: allocation overview and progress over time remain trustworthy and usable as reports grow.

### What to build

- Verify and harden desktop/mobile usability of generated reports.
- Keep Quarto report output and built-in dashboard behavior aligned while compatibility aliases remain.
- Add report-level diagnostics when trust/reconciliation issues affect displayed totals.

### Acceptance criteria

- [ ] Add mobile/desktop report usability checks or documented manual QA criteria.
- [ ] Surface reconciliation/data-quality warnings in generated reports.
- [ ] Keep deprecated visualization aliases covered until removal policy is decided.

---

## Phase 4A remainder (P0/P1): Dividend/Income + Onboarding Hardening

**User stories**: dividend automation, easy self-hosted start.

### What to build

- Dividend/income automation:
  - normalize dividend, interest, and cashflow activity variants from all first-party importers;
  - monthly/yearly income summaries;
  - report slices for income by portfolio, asset type, instrument, currency, and tax bucket where available.
- Beginner onboarding:
  - guided import checklist for first successful migration;
  - stronger docs/tests around the happy path from bootstrap to first report.

### Acceptance criteria

- [ ] Roll up dividend and interest events into monthly/yearly income views.
- [ ] Expose income views through CLI/report artifacts.
- [ ] Ensure all first-party importers map dividend/interest/cashflow events consistently.
- [ ] Enable new users to run bootstrap + first import using a documented happy path in under 15 minutes.

---

## Phase 5 remainder (P1): Full Plugin API + SDK Hardening

**User stories**: community-contributed adapters across the full pipeline and shared asset-type packs.

### What to build

Expand from the shipped import/catalog/output/storage foundation to full lifecycle/cross-cutting coverage:

- Complete hook coverage for lifecycle plugin types not yet implemented:
  - `transform`
  - `enrichment`
  - `strategy/decision`
  - `execution`
- Add or stabilize cross-cutting hooks and contracts:
  - `risk/compliance`
  - `auth/security`
  - `notification`
  - `simulation/backtest`
  - orchestration policies for multi-step plugin pipelines.
- Harden SDK scaffolding and examples for each supported plugin type.
- Keep compatibility checks and fixture-based contract tests broad enough for community plugin packs.

### Acceptance criteria

- [ ] Define and document hooks for `transform`, `enrichment`, `strategy/decision`, and `execution` plugins.
- [ ] Define and document `risk/compliance`, `auth/security`, `notification`, and `simulation/backtest` plugin contracts.
- [ ] Add SDK templates/examples beyond source-input plugins.
- [ ] Check plugin fixtures against schema and hook contracts in CI for every supported plugin type.
- [ ] Publish compatibility policy for breaking hook or manifest changes.

---

## Phase 5A remainder (P1): Data Quality Guardrails + Auto-Refresh + Paper Portfolio Policies

**User stories**: no-surprises operation, low-friction recurring updates, safe experimentation.

### What to build

- Data quality guardrails:
  - drift detection between activities and holdings;
  - policy-driven warnings vs blocking failures;
  - dashboard/report surfacing for guardrail findings.
- Scheduled refresh:
  - recurring snapshot/import orchestration for end-of-day updates;
  - diagnostics for scheduled run failures.
- Paper/experimental portfolio policy hardening:
  - explicit inclusion/exclusion rules in consolidated views;
  - labels and safeguards to prevent accidental mixing with real totals.

### Acceptance criteria

- [ ] Run drift guardrail checks consistently and surface machine-readable issue codes.
- [ ] Allow scheduled runs to append snapshots and emit import/validation diagnostics.
- [ ] Exclude paper portfolios from real portfolio totals by default with explicit opt-in for rollups.
- [ ] Surface scheduled-run and guardrail status in reports.

---

## Phase 6 (P2): Interchange + Advanced Analytics + AI Plugin Layer

**User stories**: richer analysis and portability ecosystem.

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
