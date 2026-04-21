# Native Multi-Currency Engine Design (P0)

## Goal
Eliminate manual per-holding FX entry as the default workflow by introducing automatic FX history ingestion and deterministic FX locking at snapshot time.

## Problem
Today, non-base holdings require `holding.metadata.fx_rate_to_base` to aggregate correctly. This is manual, error-prone, and not naturally auditable over time.

## Scope (P0)
- Introduce a native FX history journal (`data/fx_rates.jsonl`).
- Automatically ingest missing FX rates at snapshot time.
- Lock FX rates used by a snapshot directly in that snapshot row metadata.
- Keep backward compatibility with manual `metadata.fx_rate_to_base` as a fallback path.

## Out of Scope (P0)
- Intraday FX bars.
- Multi-provider smart routing.
- Historical snapshot recomputation pipeline.

## Data Model
### FX history journal row
```json
{
  "as_of_date": "2026-04-21",
  "base_currency": "BRL",
  "quote_currency": "USD",
  "rate_to_base": 5.25,
  "source": "frankfurter",
  "ingested_at": "2026-04-21T18:00:00Z"
}
```

### Snapshot FX lock metadata
```json
{
  "metadata": {
    "fx_lock": {
      "base_currency": "BRL",
      "snapshot_timestamp": "2026-04-21T23:59:59Z",
      "rates_to_base": {"USD": 5.25},
      "rate_dates": {"USD": "2026-04-21"},
      "sources": {"USD": "history"}
    }
  }
}
```

## Architecture
- Add `src/rikdom/fx.py` for FX history loading, lookup, fetching, and lock construction.
- Extend aggregation to accept `fx_rates_to_base` as first-class conversion context.
- Update snapshot command flow:
  1. Determine snapshot timestamp.
  2. Build FX lock (load history, auto-ingest missing rates).
  3. Aggregate portfolio with locked rates.
  4. Persist snapshot with `metadata.fx_lock`.

## Error Handling
- Missing FX after fetch attempt yields warning and skips affected holding conversion.
- Network/API failures degrade gracefully to warnings; no crash for user workflow.
- Manual `metadata.fx_rate_to_base` remains valid and emits compatibility warning.

## Testing Strategy
- Unit tests for FX history resolution and ingestion behavior.
- Aggregation tests for new conversion precedence (`fx_rates_to_base` > metadata fallback).
- Snapshot tests for FX lock metadata persistence.
- CLI integration test for `snapshot` invoking FX lock path.

## Acceptance Criteria
- Snapshot works without per-holding manual FX metadata when FX history/fetch is available.
- Snapshot row contains explicit FX lock metadata for deterministic replay.
- Existing manual FX metadata still works (compat mode).
- Existing non-FX flows remain unchanged.
