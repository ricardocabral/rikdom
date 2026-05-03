# Multi-Currency Engine

This page explains how rikdom handles multi-currency portfolios at snapshot
time and why the design favors locked, history-backed FX rates over
per-holding ad-hoc rates. For the operational recipe see
[work with multi-currency holdings](../how-to/work-with-multi-currency.md);
for the on-disk fields see
[FX snapshot fields reference](../reference/fx-snapshot-fields.md).

## How snapshot valuation works

When you run `rikdom snapshot`, rikdom performs this flow:

1. Inspect all holding currencies in the portfolio.
2. For each non-base currency, read the best available historical rate from
   `fx_rates.jsonl` for the snapshot date.
3. If a rate is missing, auto-fetch it and append it to `fx_rates.jsonl`.
4. Aggregate holdings using the resolved FX rates.
5. Persist the snapshot with `metadata.fx_lock` containing `rates_to_base`,
   `rate_dates`, and `sources`.

This makes snapshot valuation deterministic and auditable over time: a
re-run on a past snapshot row reproduces its base-currency totals exactly.

## Why a snapshot-time lock

Without a lock, recomputing a year-old snapshot with today's FX rates would
yield a different total — making historical performance numbers shift under
the user's feet. The lock pins the conversion context at the moment the
snapshot was taken so the row's totals stay stable forever.

## Compatibility fallback

If a holding still carries `metadata.fx_rate_to_base` (older portfolios),
rikdom uses it as a fallback and emits `TRUST_FX_FALLBACK_USED`. The total
is correct under the recorded rate, but the rate did not come from the
auditable FX history, so the trust report cannot pin a timestamp/source.
Migrating to history-driven FX is a one-direction trip: once the history
file has a rate, the fallback is never preferred again.

## See also

- [Work with multi-currency holdings](../how-to/work-with-multi-currency.md)
- [FX snapshot fields reference](../reference/fx-snapshot-fields.md)
- [Calculation trust](calculation-trust.md)
