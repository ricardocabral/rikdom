# Native Multi-Currency Engine (P0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual per-holding FX conversion as the default path with automatic FX history ingestion and snapshot-time FX locking.

**Architecture:** Add an FX history module and route snapshot aggregation through a locked FX context. Keep manual metadata FX as fallback compatibility only.

**Tech Stack:** Python 3.12, argparse CLI, JSON/JSONL storage, unittest.

---

### Task 1: Add red tests for FX history and conversion precedence

**Files:**
- Create: `tests/test_fx.py`
- Modify: `tests/test_aggregate.py`
- Create: `tests/test_snapshot_fx_lock.py`

- [ ] **Step 1: Write failing tests for FX history resolution and auto-ingest append behavior**
- [ ] **Step 2: Write failing aggregate test for `fx_rates_to_base` precedence and metadata fallback**
- [ ] **Step 3: Write failing snapshot test for `metadata.fx_lock` persistence**
- [ ] **Step 4: Run targeted tests and confirm failures**

### Task 2: Implement FX module and aggregate integration

**Files:**
- Create: `src/rikdom/fx.py`
- Modify: `src/rikdom/aggregate.py`

- [ ] **Step 1: Implement FX history row parsing/indexing and date-aware lookup**
- [ ] **Step 2: Implement provider fetch + append for missing currencies**
- [ ] **Step 3: Add aggregate support for explicit `fx_rates_to_base` conversion context**
- [ ] **Step 4: Re-run targeted tests and confirm green**

### Task 3: Wire snapshot flow and CLI defaults

**Files:**
- Modify: `src/rikdom/snapshot.py`
- Modify: `src/rikdom/cli.py`
- Modify: `tests/test_cli_default_bootstrap.py`

- [ ] **Step 1: Add default FX history paths and bootstrapping behavior**
- [ ] **Step 2: Build snapshot FX lock before aggregation and persist it into snapshot metadata**
- [ ] **Step 3: Add CLI flags for fx history path and auto-ingest toggle**
- [ ] **Step 4: Add/adjust CLI tests**

### Task 4: Fixtures and docs

**Files:**
- Create: `data-sample/fx_rates.jsonl`
- Modify: `README.md`
- Modify: `plugins/csv-generic/README.md`

- [ ] **Step 1: Add sample FX history file**
- [ ] **Step 2: Update docs to describe default FX workflow and compatibility fallback**
- [ ] **Step 3: Run full test suite and finalize**
