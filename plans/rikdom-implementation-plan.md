# Plan: rikdom v0.1-v0.3

> Source PRD: initial user brief in Codex thread (2026-04-20)

## Architectural decisions

Durable decisions applied across phases:

- **Storage**: local `JSON` (`portfolio.json`) + append-only `JSONL` snapshots.
- **Schema contract**: JSON Schema 2020-12 + explicit `schema_uri` and semantic `schema_version`.
- **Data model**: immutable `activities` ledger + derived `projections`.
- **Import boundary**: plugin parsers output normalized statement JSON with provenance.
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

### Acceptance criteria

- [ ] Writes are atomic (temp+rename or equivalent strategy).
- [ ] Append-only history is documented and test-covered.
- [ ] Backup/restore metadata strategy is documented.

---

## Phase 3 (P0): Import Pipeline + Idempotency + Provenance

**User stories**: safe recurring imports from providers into local files

### What to build

Implement import merge behavior with dedup keys, source references, and import run tracking.

### Acceptance criteria

- [ ] Import commands capture provenance fields.
- [ ] Duplicate imports are detected deterministically.
- [ ] Import reports expose inserted/updated/skipped counts.

---

## Phase 4 (P0): Minimal Visualization

**User stories**: allocation overview and progress over time

### What to build

Generate static dashboard from snapshots and current portfolio projections.

### Acceptance criteria

- [ ] Total value, timeline, and class allocation render offline.
- [ ] Dashboard is usable on desktop and mobile.
- [ ] Output requires no external services.

---

## Phase 5 (P1): Plugin API + SDK + Contract Tests

**User stories**: community-contributed statement import adapters

### What to build

Define stable plugin API, provide SDK scaffolding, and add fixture-based contract tests.

### Acceptance criteria

- [ ] Plugin manifest and output schema are versioned.
- [ ] SDK template reduces boilerplate for new plugins.
- [ ] CI checks plugin fixtures against schema contracts.

---

## Phase 6 (P1/P2): Advanced Valuation + Interchange + Analytics

**User stories**: richer analysis and portability ecosystem

### What to build

Add quote/FX history model, export package format with checksums, and extended analytics roadmap.

### Acceptance criteria

- [ ] Quote/FX model supports deterministic valuation snapshots.
- [ ] Export package is self-describing and integrity-checked.
- [ ] Advanced analytics scope is captured in roadmap issues.
