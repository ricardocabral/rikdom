# Calculation Trust and Reconciliation Reports

This document explains rikdom's Calculation Trust UX and Reconciliation
Reports — the contracts that make portfolio totals reproducible and surface
actionable data-quality issues. For the issue-code table, see
[reconciliation codes reference](../reference/reconciliation-codes.md). For
FX-specific behavior, see
[multi-currency engine](multi-currency-engine.md).

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
| `out/reports/holding_trust.{json,md}` | Per-holding traceability artifact | shipped |
| `out/reports/reconciliation.{json,md}` | Aggregated reconciliation report | shipped |
| `rikdom reconcile` CLI | Generates the two reports above | shipped |

## The `Finding` shape

Each structured finding emitted by `aggregate_portfolio` has the following
fields:

```text
code           Stable identifier (see reconciliation codes reference)
severity       info | warning | error
message        Human-readable description
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

For each holding, the trust report records:

- `source_amount`, `source_currency` from `holding.market_value`
- `fx_rate`, `fx_timestamp`, `fx_source` resolved from `fx_rates_to_base`
  (preferred) or `metadata.fx_rate_to_base` (compatibility fallback —
  flagged as `TRUST_FX_FALLBACK_USED`)
- `base_amount`; report-level `generated_at` records generation, not a quote date

Summing `base_amount` across holdings yields `total_value_base`. Any FX
gap is reported as `RECON_FX_MISSING` and the affected holding is excluded
from the total — making the gap directly visible rather than silently
zeroing out.

For activity-derived ledgers (cash drift, quantity replay), the same
`Finding` records identify the offending activities and their expected vs
observed deltas, so users can locate the source rows in their importer
inputs.

## See also

- [Reconciliation codes reference](../reference/reconciliation-codes.md) — every issue code.
- [Multi-currency engine](multi-currency-engine.md) — FX resolution.
- `src/rikdom/aggregate.py` — emission sites for each finding.

## Current values, history, and corrected events

Current total is the sum of included holdings' market values converted with the
selected FX context. Quantities and activities check consistency; their cashflows
are not added again to the current holdings total. Core retains calculation
precision; output plugins choose display formatting. Missing/invalid reporting
currency is an error, not an implicit USD selection.

For example, 200 JPY at an explicitly cached 0.006123 EUR/JPY contributes
1.2246 EUR. A second 10 EUR holding gives 11.2246 EUR. A 100 GBP holding without
FX is excluded and receives `RECON_FX_MISSING`; its value is not silently assumed
to be zero. Reproduce the total by summing the non-excluded `base_amount` entries
in `holding_trust.json` and inspecting its invariant. Available FX dates/providers
come from the lock; metadata-only rates can have an unknown effective date.
Report generation time never fills that gap.

For a quantity check, a dated position of 3 units against an explicitly covered
buy of 2 is a mismatch. Without the account scope, source period, inception/zero
opening evidence, and compatible trade basis, it is `not_computable`, even when
numbers happen to match. Reports distinguish these states. The current workflow
does not infer settled quantities, a settlement calendar, or missing purchases.

A manual correction appends a linked replacement and preserves the original.
Correction-aware calculations count the latest replacement once. This introduces
schema 2.0 financial semantics; uncorrected 1.x remains supported. See the
[manual-entry guide](../how-to/enter-and-correct-activities.md) for preview/write,
replays, and dependent-lot limitations.

Reports distinguish current holdings from historical snapshot totals. To reproduce
a historical observation, use its original holdings and saved `metadata.fx_lock`.
Today's `reconcile` against a current portfolio does not reconstruct older holdings.
Missing archived inputs remain a limitation, even if the rate lock survives.

Run `rikdom reconcile --data-dir data --out-root out` for the four trust artifacts,
or add `--reconcile` to a successful import. Import previews include candidate
quality/coverage summaries and write no artifacts. Quarto renders the same core
aggregate/trust results and links to the local JSON/Markdown files.
