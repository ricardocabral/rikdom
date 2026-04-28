# Calculation Trust and Reconciliation Reports

This document describes Rikdom's Calculation Trust UX and Reconciliation
Reports — the contracts that make portfolio totals reproducible and surface
actionable data-quality issues.

## Goals

- Numbers must be correct, and the user must be able to see *how* a number
  was computed.
- Every aggregated value should be traceable to its source amount, FX
  context, and timestamp.
- Reconciliation findings should carry stable issue codes so reports can be
  consumed by both humans and CI/UI.

## Components

| Component | Role | Status |
| --- | --- | --- |
| `src/rikdom/reconciliation/codes.py` | Frozen registry of issue codes + default severities | shipped |
| `src/rikdom/reconciliation/findings.py` | `Finding` dataclass and `record_finding` helper | shipped |
| `aggregate_portfolio()` `findings` field | Structured siblings of the existing `warnings` strings | shipped |
| `out/reports/holding_trust.{json,md}` | Per-holding traceability artifact | planned |
| `out/reports/reconciliation.{json,md}` | Aggregated reconciliation report | planned |
| `rikdom reconcile` CLI | Generates the two reports above | planned |

## The `Finding` shape

Each structured finding emitted by `aggregate_portfolio` has the following
fields:

```text
code           Stable identifier (see docs/reconciliation-codes.md)
severity       info | warning | error
message        Human-readable description (matches the legacy warning string)
scope          Where in the data model the finding applies (e.g. "holding")
refs           Identifier map, e.g. {"holding_id": "h-petr4"}
observed       Observed values (e.g. holding vs ledger quantity)
expected       Expected condition (e.g. drift_within tolerance)
suggested_fix  How a user can resolve the finding
```

`Finding.to_dict()` omits empty fields, keeping JSON output compact.

## Backward compatibility

The pre-existing `AggregateResult.warnings: list[str]` is unchanged in
shape and content. `findings` is a new sibling field, defaulting to an
empty list, that mirrors each warning with a structured record. Tools that
already consume `warnings` continue to work.

## How to reproduce a portfolio total

The aggregation pipeline computes each holding's base-currency value as:

```text
base_amount = holding.market_value.amount × fx_rate(currency → base, at timestamp)
```

For each holding, the trust report (planned) will record:

- `source_amount`, `source_currency` from `holding.market_value`
- `fx_rate`, `fx_timestamp`, `fx_source` resolved from `fx_rates_to_base`
  (preferred) or `metadata.fx_rate_to_base` (compatibility fallback —
  flagged as `TRUST_FX_FALLBACK_USED`)
- `base_amount`, `computed_at`

Summing `base_amount` across holdings yields `total_value_base`. Any FX
gap is reported as `RECON_FX_MISSING` and the affected holding is
excluded from the total — making the gap directly visible rather than
silently zeroing out.

For activity-derived ledgers (cash drift, quantity replay), the same
`Finding` records identify the offending activities and their expected vs
observed deltas, so users can locate the source rows in their importer
inputs.

## Acceptance criteria mapping (Phase 3A)

- [x] Stable issue codes for reconciliation findings — `ISSUE_CODES`
  registry.
- [ ] Make each computed holding value traceable to source amount + FX +
  timestamp in an exported report — trust report writer planned.
- [ ] Ensure reconciliation reports flag amount/quantity inconsistencies
  with actionable diagnostics — structured `Finding` shape ships now;
  consolidated report planned.
- [x] Document how to reproduce a portfolio total from raw holdings,
  activities, and FX history — this document.

## See also

- `docs/reconciliation-codes.md` — reference for every issue code.
- `docs/native-multi-currency-engine.md` — FX resolution and base
  currency handling.
- `src/rikdom/aggregate.py` — emission sites for each finding.
