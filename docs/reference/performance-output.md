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
unavailable), period basis and annualized XIRR basis. Benchmark comparisons
continue using the legacy `twr_pct` Dietz result.

`twr_pct`, `twr_return_pct`, `linked_twr_pct`, and `mwr_pct` are percentages (e.g. `10.0` == +10%). MWR is
annualized (365-day years); short windows therefore extrapolate to a yearly
rate. TWR is the period return — not annualized.

Either field is `null` if the input does not support a return:

- `twr_pct` is `null` when the Modified Dietz denominator is non-positive
  (no invested capital over the period).
- `mwr_pct` is `null` when the cashflow series has no sign change or XIRR
  fails to converge.

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

## FX handling

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

> Caveat: the CLI resolves an FX lock at computation time and applies it to
> historical cashflows. Although schema 1.5.0 supports `Money.fx_ref`
> provenance, this performance calculation does not use per-cashflow FX rates.

## See also

- [Compute portfolio TWR / MWR](../how-to/compute-performance.md)
- [Performance methodology](../explanation/performance-methodology.md)
