# Performance Output Reference

`rikdom performance` emits a single JSON object to stdout. This page
documents the field shape, bookend selection, and which event types feed
the cashflow series. For the math behind the numbers, see
[performance methodology](../explanation/performance-methodology.md). For
the recipe, see [compute portfolio TWR / MWR](../how-to/compute-performance.md).

## Inputs

- `data/portfolio.json` — for `settings.base_currency`, `activities[]`, and FX
  fallbacks (`metadata.fx_rate_to_base`).
- `data/snapshots.jsonl` — period-end portfolio values.
- `--flow-valuations PATH` (optional) — explicit before/after external cashflow
  evidence; version 1 portfolio-only contract below. This file is read-only.
- `data/fx_rates.jsonl` (optional) — used to resolve foreign-currency
  cashflows to base currency via the same fallback chain as `aggregate`.

## Output shape

```json
{
  "base_currency": "BRL",
  "period_start": "2026-01-31T23:59:59Z",
  "period_end": "2026-04-19T23:59:59Z",
  "start_value_base": 149300.0,
  "end_value_base": 165830.0,
  "net_external_cashflow_base": 0,
  "twr_pct": 11.071668,
  "legacy_twr_method": "modified_dietz",
  "twr_return_pct": 11.071668,
  "linked_twr_pct": null,
  "twr_method": "bookend_ratio",
  "twr_return_basis": "period",
  "twr_fallback_reason": null,
  "mwr_method": "xirr",
  "mwr_return_basis": "annualized_365_day",
  "mwr_pct": 63.455683,
  "cashflow_count": 0,
  "warnings": []
}
```

`twr_pct` retains the legacy **Modified Dietz approximation**, including when
linked evidence is supplied. `twr_return_pct` selects the best supported return;
its `twr_method` is `linked_subperiod`, `bookend_ratio`, `modified_dietz`, or
`unavailable`. `linked_twr_pct` is populated only for `linked_subperiod`.
`twr_fallback_reason` and `warnings[]` disclose missing/inconsistent boundaries,
skipped or malformed flows, undated FX, and unresolved transfer identities.
Account and strategic-bucket rows always identify their Dietz method (or
unavailable), period basis and annualized XIRR basis. Legacy benchmark
comparisons use `twr_pct`; historical FX comparisons use the selected return.

`twr_pct`, `twr_return_pct`, `linked_twr_pct`, and `mwr_pct` are percentages (e.g. `10.0` == +10%). MWR is
annualized (365-day years); short windows therefore extrapolate to a yearly
rate. TWR is the period return — not annualized.

Either field is `null` if the input does not support a return:

- `twr_pct` is `null` when the Modified Dietz denominator is non-positive
  (no invested capital over the period).
- `mwr_pct` is `null` when the cashflow series has no sign change or XIRR
  fails to converge.

## Residual growth bridge

Portfolio output adds `growth_bridge`. Python consumers, including reports, use
`performance_result_to_dict(compute_performance(...))` from `rikdom.performance`
for the same JSON contract as the CLI. Existing fields retain their meanings and
precision; optional benchmark fields retain their conditional legacy/historical
shape. Account, bucket, and instrument rows do not gain portfolio growth bridges.

For example, opening value 100, contributions 30, withdrawals 10 and closing
value 150 give:

```json
{
  "status": "complete",
  "method": "residual_growth",
  "completeness_scope": "arithmetic_reconciliation_of_supplied_inputs",
  "caveat": "Does not independently verify transaction history, snapshot FX, reported valuations, or lot gains.",
  "base_currency": "BRL",
  "period_start": "2026-01-01T00:00:00Z",
  "period_end": "2027-01-01T00:00:00Z",
  "opening_value_base": 100.0,
  "net_external_cashflow_base": 20.0,
  "investment_result_base": 30.0,
  "closing_value_base": 150.0,
  "rounding_adjustment_base": 0.0,
  "rounding_decimals": 6,
  "rounding_method": "half_even",
  "income_treatment": "embedded_in_snapshot_values_not_added_again",
  "fees_and_taxes": "embedded_in_snapshot_values_not_separately_calculated",
  "reasons": []
}
```

The bridge reuses the selected portfolio bookends, effective corrected posted
activities, signed external cashflows, and dated FX completeness. Its actual
window is `period_start` through `period_end`, including both instants. The
opening snapshot is assumed to precede an external flow exactly at its instant;
the closing snapshot is assumed to follow one at its instant, matching the
existing performance boundary convention.

`investment_result_base` is the **aggregate residual**:
`closing - opening - signed net external cashflow`. Dividends, interest and other
income already embedded in snapshots are never added again. Fees and taxes
reduce the result only to the extent they are reflected in supplied valuations
and flows; the bridge does not calculate, gross up, or separately attribute them.
A dividend receipt of 7 in the example does not change the residual from 30 to 37.

`status: complete` means only that the supplied inputs support this arithmetic
reconciliation. `completeness_scope` and `caveat` explicitly limit that claim:
ledger coverage, reported valuations and snapshot FX are not independently
verified. It is not a complete profit total, a realized/unrealized gain split,
a tax-lot calculation, or attribution of FX effects versus investment effects.
Those require additional history and valuation evidence.

`status: unavailable` sets `investment_result_base`,
`net_external_cashflow_base` and `rounding_adjustment_base` to `null`, with
`reasons[]`. Known finite bookend values remain visible; missing/invalid values
stay `null`. The bridge requires two timezone-qualified, currency-verified,
non-negative bookend valuations and a positive-duration window. Zero opening
capital and a total loss can reconcile even when a return is undefined.
Skipped/malformed external flows, naive flow timestamps, missing/stale dated FX,
undated foreign conversion and unresolved transfer identities prevent a complete
bridge. This deliberately remains conservative even where legacy compatibility
fields retain partial or approximate numeric results. Missing flow-boundary
sidecars alone do not block residual arithmetic: they are needed for linked TWR,
not the aggregate residual.

Bridge amounts are rounded to six decimal places in base-currency units with
decimal half-even rounding of the calculation's public numeric inputs. The
residual is calculated before rounding. `rounding_adjustment_base` is the signed
difference needed for the independently rounded components to reconcile:

```text
opening + net external cashflow + investment result + rounding adjustment = closing
```

Normally the adjustment is zero. For opening `1.0000004`, flow `0.0000004` and
closing `2.0000006`, the rounded bridge is `1 + 0 + 1 + 0.000001 = 2.000001`.
Amounts exceeding the finite supported numeric range make the bridge unavailable.
Consumers should use the provided fields rather than recalculate financial values
in the frontend; minor binary float representation differences are possible.

## Explicit cashflow valuation evidence

```json
{
  "version": 1,
  "scope": "portfolio",
  "base_currency": "BRL",
  "rounding_tolerance_base": 0.01,
  "valuations": [
    {
      "timestamp": "2026-01-06T00:00:00Z",
      "base_currency": "BRL",
      "pre_flow_value_base": 110.0,
      "post_flow_value_base": 160.0,
      "source": "Custodian valuation report, before and after contribution"
    }
  ]
}
```

All fields shown are required; extra fields are rejected at both levels.
`version` is integer `1`, `scope` is `portfolio`, and both currency fields must
match the portfolio base currency. Numeric fields must be finite numbers, not
booleans. `rounding_tolerance_base` must be non-negative and declares an absolute
rounding allowance in base-currency units. `source` must be nonblank.
`timestamp` must be an ISO datetime with explicit timezone; dates alone and
naive datetimes are rejected. Duplicate instants are rejected even if expressed
with different timezone offsets. Array order is irrelevant.

Each row values the **whole portfolio immediately before and after** the
aggregate of all signed external cashflows at that instant. The difference
`post_flow_value_base - pre_flow_value_base` must equal the signed ledger total
within the declared tolerance. One row covers all same-instant flows, including
net-zero groups. Retain the source report and evidence file for auditing.
Ordinary daily snapshots never imply these before/after semantics.

Only evidence inside the selected snapshot window is used; other rows are
validated but ignored. The window includes both bookend instants. At a start
cashflow the start snapshot must equal the **pre-flow** value; at an end
cashflow the end snapshot must equal the **post-flow** value, within the same
tolerance. An incompatible bookend produces a labeled Dietz fallback. Every
in-window cashflow instant needs a row, and every in-window row needs a matching
cashflow instant. Missing or inconsistent evidence gives Dietz plus a reason.
Malformed sidecars fail with an actionable error and nonzero CLI exit status.
`--flow-valuations` with `--by account`, `strategic_bucket`, or `instrument` is
rejected explicitly.

No-flow periods use a bookend ratio if the input data is complete. Positive
opening capital and a positive-duration window are required; terminal capital
may be zero (a -100% loss). Negative capital and nonfinite financial values
make the selected return unavailable. Zero capital between subperiods also
makes linking unavailable. A zero post-flow value at the terminal boundary is
allowed, since there is no subsequent subperiod to divide by it.

## Bookend snapshot selection

- **Start:** the latest snapshot at-or-before `--since` if one exists, else
  the earliest snapshot in the window.
- **End:** the latest snapshot at-or-before `--until` (or overall, if
  `--until` is omitted).

## External vs. internal cashflows

Only **external** activity events count as cashflows for performance:

| Event type     | Sign | Treatment                          |
| -------------- | ---- | ---------------------------------- |
| `contribution` |  +   | money added to portfolio           |
| `transfer_in`  |  +   | assets/cash moved in from outside  |
| `withdrawal`   |  -   | money taken out of portfolio       |
| `transfer_out` |  -   | assets/cash moved out              |

Transfer events retain the legacy external-flow treatment. The current ledger
has no supported internal-transfer pairing identity; the calculator does not
pair transfers by equal amount/date. Transfer-containing periods therefore
use a disclosed approximate Dietz result, even when evidence is supplied.
Internal-transfer reconciliation remains unresolved.

All other event types — `buy`, `sell`, `dividend`, `interest`, `fee`,
`income`, `reimbursement`, `tax_withheld`, `fx_conversion`, `split`,
`merger`, `other` — are **internal**: they reshuffle value within the
portfolio and are deliberately excluded from the cashflow series. Their
effect already shows up in the next snapshot's `portfolio_value_base`.

Activities with an explicit non-posted `status` (e.g. `pending`, `cancelled`)
are skipped. A missing or blank `status` is treated as `posted` and included
— this matches `aggregate`.

## Historical FX mode

`--historical-fx CONFIG` selects the [local dated FX contract](historical-fx.md).
Portfolio and account/bucket rows add `fx_status` and `fx_evidence`.
`fx_status` is `complete`, `unavailable`, or `legacy_approximate`; completeness
refers to required cashflow conversions, not independent snapshot valuations.
Missing/stale required historical FX sets affected returns and net contributions
to `null`, with warnings and retained lookup evidence. Other scopes remain usable
when their own required data is complete.

In this mode benchmark output also exposes `period_start`, `period_end`,
`native_currency`, `native_twr_pct`, `return_convention`, `comparison_status`,
`data_provenance`, and `fx_evidence`. [Benchmark FX rules](benchmark-fx.md)
define when common-currency excess return is comparable. The selected
`twr_return_pct` is used for that comparison. Legacy mode continues comparing
the Dietz field.

## FX handling (legacy mode)

Foreign-currency cashflows are converted to base currency using the same
fallback chain as `aggregate_portfolio`:

1. `fx_rates_to_base[CCY]` from the snapshot FX lock (loaded from
   `--fx-history`).
2. `metadata.fx_rate_to_base` on the activity itself.

These rates are undated for this calculation. A converted foreign cashflow
always warns that history is approximate and prevents an exact linked-return
claim; a sidecar cannot supply or repair missing historical FX.

If neither resolves, the cashflow is **skipped with a warning** rather than
blocking the whole computation; the resulting TWR/MWR is still emitted but
flagged as approximate via `warnings[]`.

## Per-instrument output

`--by instrument` emits `by_instrument`, an array in each holding's native
transaction currency. It uses purchases and distributions as cashflows across
the instrument boundary; portfolio-level external flow rules remain unchanged.

| Field | Meaning |
| --- | --- |
| `holding_id`, `ticker`, `currency` | Instrument identity and transaction currency. |
| `status` | `complete` or `incomplete_history`. |
| `period_start` | First valid acquisition cashflow. |
| `period_end`, `terminal_value` | Dated valuation or explicit proceeds supplied by the caller. |
| `valuation_basis` | `gross_market_value` or `explicit_terminal_value`; taxes are not inferred. |
| `observed_buy_outflows` | Recorded purchases including attached fees and taxes. |
| `observed_sell_inflows` | Recorded sales after attached fees and taxes. |
| `observed_distributions` | Recorded dividend, interest, income, amortization and reimbursement receipts; gross-basis amounts are reduced by attached costs, while net-basis amounts are used as recorded. |
| `observed_fees`, `observed_taxes` | Costs recorded in supported events, including attached costs. |
| `observed_net_cashflow` | Recorded investor cashflows, excluding terminal value. |
| `profit_amount` | Terminal value plus net cashflows; `null` for incomplete history. |
| `xirr_pct` | Annualized investor return in percent; `null` for incomplete or unsolvable histories. |
| `cashflows` | Auditable dated investor cashflows, including the terminal value when available. |
| `warnings` | Missing coverage, stale valuations, ambiguous identities, unsupported movements or inconsistent amounts. |

Observed totals summarize the records present; they are not complete lifetime
totals unless the history has been reconciled. Corrections are resolved before
calculating returns, and pending and cancelled activities are excluded. For
distributions marked net, the recorded amount is the receipt and attached
charges are not deducted again. An unknown amount basis makes the full return
unavailable; see the [income amount-basis contract](cli.md#income). Signed
corporate-action quantity deltas carry no investment cash by themselves. Unhandled cash components prevent a complete return.

Full returns require the declared coverage to include the first acquisition
through valuation, without declared gaps or inconsistent quantities. Explicit
cash settlement dates take precedence. Tax lots help audit cost basis but do not
substitute for missing acquisition cashflows. The calculator uses no implicit
FX conversion and does not calculate Brazilian monthly capital gains tax or
fixed-income redemption taxes.

## Scope and limits

The CLI also supports `--by account` and `--by strategic_bucket`, using
`totals.by_account` and `totals.by_strategic_bucket` snapshot bookends,
respectively. Strategic-bucket output requires a policy. A supplied policy can
also enable benchmark comparisons. Instrument mode uses the activity ledger
and a terminal valuation instead of snapshot bookends.

> Legacy-mode caveat: without `--historical-fx`, the CLI resolves an FX lock
> at computation time and applies it to historical cashflows. Although schema 1.5.0 supports `Money.fx_ref`
> provenance, this performance calculation does not use per-cashflow FX rates.

## See also

- [Compute portfolio TWR / MWR](../how-to/compute-performance.md)
- [Performance methodology](../explanation/performance-methodology.md)
