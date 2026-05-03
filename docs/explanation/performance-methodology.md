# Performance Methodology

This page explains *why* the performance module reports both Modified Dietz
TWR and XIRR MWR, and the math behind each. For the recipe, see
[compute portfolio TWR / MWR](../how-to/compute-performance.md). For the
output shape, see [performance output reference](../reference/performance-output.md).

## Why two return measures

- **Time-weighted return (TWR)** strips out the impact of contribution
  timing, isolating "how did the portfolio's investments perform?". It is
  the right number for comparing portfolios or evaluating a strategy.
- **Money-weighted return (MWR)** *includes* contribution timing, answering
  "what return did the investor's money earn?". It is the right number for
  comparing your outcome to a personal hurdle rate.

Both reflect the same activity ledger and snapshot history; reporting both
lets the same data answer both questions without the user having to
reconstruct cashflows.

## Modified Dietz (TWR)

```
denom = start_value + Σ w_i · CF_i
TWR   = (end_value − start_value − Σ CF_i) / denom
where w_i = (period_end − cf_time) / (period_end − period_start)
```

Modified Dietz is a closed-form approximation of TWR that needs only
period-end values and externally-dated cashflows — exactly what rikdom
already records. The approximation degrades when there are very large
cashflows close to a period boundary; for that regime, sub-period TWR
(linking daily TWRs) is the standard improvement, and is a candidate for
future work.

## XIRR (MWR)

The MWR is the IRR of the irregular cashflow stream `[start_value (negative
at period_start), … external CFs (sign-flipped to investor perspective) …,
end_value (positive at period_end)]`.

Implementation: Newton's method with bisection fallback over `[-0.999999,
10.0]`. Bisection guarantees convergence for any series with at least one
sign change.

`mwr_pct` is annualized using a 365-day year; short windows extrapolate.

## What counts as a cashflow

Only **external** activity events feed the cashflow series — see the
[external vs. internal cashflows](../reference/performance-output.md#external-vs-internal-cashflows)
table. Internal events (`buy`, `sell`, `dividend`, etc.) reshape value
within the portfolio and would double-count if added to the series, since
the next snapshot already reflects them.

## Why FX gaps warn instead of fail

A missing FX rate for a single foreign-currency cashflow is a data-quality
problem, not a reason to block the user from seeing returns on the rest of
the portfolio. The resolver skips the cashflow with a `warnings[]` entry
so the user gets a usable number plus an actionable diagnostic.

## See also

- [Performance output reference](../reference/performance-output.md)
- [Compute portfolio TWR / MWR](../how-to/compute-performance.md)
- [Calculation trust](calculation-trust.md) — broader reproducibility design.
