# Reconciliation Issue Codes

Stable identifiers for structured findings emitted by the aggregation
pipeline. Codes are part of the public reporting contract: existing codes
will not be renamed or repurposed without a deprecation cycle. New codes
append to the registry in `src/rikdom/reconciliation/codes.py`.

See `docs/calculation-trust.md` for the broader Calculation Trust design.

## Severity levels

| Severity | Meaning |
| --- | --- |
| `info` | Informational; does not affect trust in totals. |
| `warning` | Data-quality concern; totals are still computed but may be incomplete. |
| `error` | Blocks trust in the affected total; emitted when `strict=True` for FX gaps. |

## Codes

| Code | Default severity | Scope | Meaning | Suggested fix |
| --- | --- | --- | --- | --- |
| `RECON_FX_MISSING` | warning | holding/activity | No FX rate available to convert the source currency to the portfolio base currency. The affected amount is excluded from totals (or raised as an error in strict mode). | Add the missing rate to `fx_rates_to_base` from authoritative FX history, or set `metadata.fx_rate_to_base` on the affected record. |
| `TRUST_FX_FALLBACK_USED` | warning | holding/activity | Conversion succeeded only by falling back to `metadata.fx_rate_to_base`. The total is correct under the recorded rate, but the rate did not come from the FX history. | Provide the rate via authoritative `fx_rates_to_base` so the trust report can record an FX timestamp/source. |
| `RECON_INVALID_MONEY` | warning | holding/activity | A money object (e.g. `market_value`, `money`, `fees`) is missing, has a non-object shape, or has a malformed `amount`/`currency`. | Ensure money objects follow `{amount: number, currency: ISO-4217 code}`. |
| `RECON_MALFORMED_HOLDING` | warning | portfolio | A holding entry is not a JSON object and was skipped. | Ensure each holding entry is an object with the expected fields. |
| `RECON_LOOKTHROUGH_NON_POSITIVE_WEIGHT` | warning | holding | A holding's look-through `economic_exposure.breakdown` weights sum to zero or less; the exposure was assigned to `__unclassified__`. | Set `weight_pct` values that sum to a positive total. |
| `RECON_QTY_LEDGER_MISMATCH` | warning | holding | The declared holding quantity does not match the activity-ledger replay (`buy + transfer_in − sell − transfer_out`). | Reconcile activities against the holding: fix missing buy/sell/transfer/split events or correct the holding quantity. |
| `RECON_CASH_DRIFT` | warning | portfolio | Total cash declared by `cash_equivalents` holdings does not match the cash activity ledger within the configured tolerance. | Verify cash holdings against the activity ledger; add missing deposit/withdrawal/dividend events or correct the cash holding amount. |

## Programmatic access

```python
from rikdom.reconciliation import ISSUE_CODES, Severity

for code, severity in ISSUE_CODES.items():
    print(code, severity.value)
```

`ISSUE_CODES` is an immutable mapping (`MappingProxyType`); attempts to
mutate it raise `TypeError`.

## Adding a new code

1. Append the code and its default `Severity` in `src/rikdom/reconciliation/codes.py`.
2. Add a row to the table above describing scope, meaning, and suggested fix.
3. Emit the finding from the aggregation site using `record_finding(...)`.
4. Add a test case in `tests/test_reconciliation_findings.py` asserting the code
   surfaces under the expected condition.
