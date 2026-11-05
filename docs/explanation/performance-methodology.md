# Performance Methodology

This page explains *why* the performance module reports linked TWR when explicit evidence is available,
a disclosed Modified Dietz approximation otherwise, and XIRR MWR, and the math behind each. For the recipe, see
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

## Linked subperiod TWR

Explicit portfolio valuations immediately before and after each aggregate
external cashflow isolate investment growth from money crossing the boundary:

```
1 + TWR = (first_pre_flow / opening_value)
          × (next_pre_flow / previous_post_flow) × ...
          × (terminal_value / last_post_flow)
```

For example, `100 → 110`, contribution `+50 → 160`, then `160 → 176`
gives `(110 / 100) × (176 / 160) - 1 = 21%`. A withdrawal of 50 instead
leaves 60; growth to 66 gives the same 21%. Same-instant flows are aggregated
before reconciling the pre/post difference. This is a period return, not an
annualized return. With no flows, the bookend ratio suffices.

The optional versioned sidecar declares the currency, source and rounding
tolerance. It is independent of ordinary daily snapshots: a timestamp alone
cannot establish which side of a flow a valuation represents. See the exact
[sidecar and boundary contract](../reference/performance-output.md#explicit-cashflow-valuation-evidence).
Missing or inconsistent evidence produces a labeled Dietz fallback, while
invalid financial capital can make the return unavailable. No claim of exact
linked history is made for skipped/malformed flows, undated foreign FX or
unresolved transfer identities.

## Modified Dietz approximation

```
denom = start_value + Σ w_i · CF_i
TWR   = (end_value − start_value − Σ CF_i) / denom
where w_i = (period_end − cf_time) / (period_end − period_start)
```

Modified Dietz is a closed-form approximation of TWR that needs only
period-end values and externally-dated cashflows — exactly what rikdom
already records. The approximation degrades when there are very large
cashflows close to a period boundary. Linked TWR is available only when explicit
before/after flow evidence establishes the required boundaries. The legacy
`twr_pct` continues to hold Dietz; use `twr_return_pct` and `twr_method` to select
and identify the supported result.

## XIRR (MWR)

The MWR is the IRR of the irregular cashflow stream `[start_value (negative
at period_start), … external CFs (sign-flipped to investor perspective) …,
end_value (positive at period_end)]`.

Implementation: Newton's method with bisection fallback over `[-0.999999,
10.0]`. A sign change alone does not guarantee a solution within that range; an
unsolvable series yields an unavailable MWR.

`mwr_pct` is annualized using a 365-day year; short windows extrapolate.

## What counts as a cashflow

Only **external** activity events feed the cashflow series — see the
[external vs. internal cashflows](../reference/performance-output.md#external-vs-internal-cashflows)
table. Internal events (`buy`, `sell`, `dividend`, etc.) reshape value
within the portfolio and would double-count if added to the series, since
the next snapshot already reflects them. Instrument returns use a different
boundary: purchases and distributions cross between the investor and the
instrument. See [per-instrument output](../reference/performance-output.md#per-instrument-output).

## Historical FX completeness

With `--historical-fx`, each foreign external cashflow uses a selected local
observation at its effective timestamp. Missing, stale, or invalid conversion
evidence makes affected returns and net contributions unavailable; skipping that
cashflow would misstate investment growth. Other account/bucket scopes can remain
usable when their own inputs are complete. The supplied snapshot and flow-boundary
valuations still need independent reporting-currency evidence.

The same [dated FX resolver](../reference/historical-fx.md) converts benchmark
bookends. [Comparable excess return](../reference/benchmark-fx.md) additionally
requires matching windows, sourced total-return inputs, and complete active
composite components. A window with only one snapshot cannot establish a return;
a malformed optional benchmark becomes unavailable without discarding usable
portfolio results.

## Contributions versus residual investment growth

The portfolio growth bridge answers how much of the change in supplied values
remains after recorded net contributions:

```text
investment result = closing value - opening value - net external cashflow
```

For opening 100, contributions 30, withdrawals 10 and closing 150, this residual
is 30. Income already reflected in closing value is part of that 30; adding a
separate dividend total would count it twice. Fees and taxes affect the residual
only as embedded in supplied valuations and cashflows. No separate net-of-fee,
net-of-tax or gross return is inferred.

A residual needs no subperiod valuation boundaries. It does need usable bookends
and complete, unapproximated recorded external cashflow conversion. It therefore
can be available alongside a disclosed Dietz approximation, while skipped flows,
undated FX and unresolved transfers make the bridge unavailable. The bridge's
`complete` status describes supplied-input arithmetic, not independently verified
ledger coverage, snapshot FX, valuations, realized gains or tax-lot history.
It is an aggregate growth reconciliation, not full profit attribution.
See the [bridge contract](../reference/performance-output.md#residual-growth-bridge)
for eligibility, explicit limitations and rounding adjustments.

## Why legacy FX gaps warn instead of fail

Without `--historical-fx`, a missing FX rate for a single foreign-currency
cashflow retains the compatibility behavior: it is a data-quality problem,
rather than a command failure. The resolver skips the cashflow with a `warnings[]` entry
so the user gets a usable number plus an actionable diagnostic.

## See also

- [Performance output reference](../reference/performance-output.md)
- [Compute portfolio TWR / MWR](../how-to/compute-performance.md)
- [Calculation trust](calculation-trust.md) — broader reproducibility design.
