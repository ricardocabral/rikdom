# Plan: rikdom v0.1

> Source PRD: initial user brief in Codex thread (2026-04-20)

## Architectural decisions

Durable decisions applied across phases:

- **Storage**: local `JSON` (`portfolio.json`) + append-only `JSONL` (`snapshots.jsonl`).
- **Schema**: JSON Schema 2020-12 with strict core and extension slots.
- **Key models**: `asset_type_catalog`, `holdings`, `snapshot totals`.
- **Plugin boundary**: parser plugins emit normalized JSON to stdout.
- **Visualization**: static offline HTML generated from local data.
- **Agent interoperability**: instruction files under `agents/` for Codex/Claude.

---

## Phase 1: Schema Foundation And Storage

**User stories**: durable portfolio definition, local persistence, extensibility by country

### What to build

Define base schema files, sample data, and validation rules to guarantee portable long-term representation while preserving extension namespaces.

### Acceptance criteria

- [ ] `schema/portfolio.schema.json` documents core objects and extension slots.
- [ ] `schema/snapshot.schema.json` supports append-only time series records.
- [ ] Example `data/portfolio.json` and `data/snapshots.jsonl` validate.

---

## Phase 2: CLI Operations

**User stories**: inspect and maintain local portfolio files without external services

### What to build

Implement command-line operations for validation, aggregation, snapshot append, and import merge with deterministic outputs.

### Acceptance criteria

- [ ] `rikdom validate` reports actionable errors.
- [ ] `rikdom aggregate` outputs totals by asset class in base currency.
- [ ] `rikdom snapshot` appends snapshot lines.
- [ ] `rikdom import-statement` merges plugin output safely.

---

## Phase 3: Minimal Visualization

**User stories**: view allocation and progress over time from local files

### What to build

Generate an offline HTML dashboard with core metrics, time-series trend, and class allocation bars.

### Acceptance criteria

- [ ] `rikdom visualize` writes `out/dashboard.html`.
- [ ] Dashboard works without network access.
- [ ] Mobile and desktop layouts are usable.

---

## Phase 4: Plugin Ecosystem Bootstrap

**User stories**: simplify onboarding of statement imports from external platforms

### What to build

Document plugin contract, include one reference plugin, and define contribution guidelines.

### Acceptance criteria

- [ ] Plugin manifest contract documented.
- [ ] `csv-generic` example works end-to-end.
- [ ] Contribution guidance exists for community plugin authors.

---

## Phase 5: Agent Skills And Roadmap Governance

**User stories**: enable LLM-assisted analysis and schema evolution

### What to build

Provide agent instruction files, roadmap issue set, and governance docs for schema versioning and backward compatibility.

### Acceptance criteria

- [ ] Codex and Claude instruction files exist.
- [ ] Roadmap issues are defined and publishable to GitHub.
- [ ] Schema evolution rules are documented.
