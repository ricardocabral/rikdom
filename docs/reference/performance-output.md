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
  "mwr_pct": 63.455683,
  "cashflow_count": 0,
  "warnings": []
}
```

`twr_pct` and `mwr_pct` are percentages (e.g. `10.0` == +10%). MWR is
annualized (365-day years); short windows therefore extrapolate to a yearly
rate. TWR is the period return — not annualized.

Either field is `null` if the input does not support a return:

- `twr_pct` is `null` when the Modified Dietz denominator is non-positive
  (no invested capital over the period).
- `mwr_pct` is `null` when the cashflow series has no sign change or XIRR
  fails to converge.

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

If neither resolves, the cashflow is **skipped with a warning** rather than
blocking the whole computation; the resulting TWR/MWR is still emitted but
flagged as approximate via `warnings[]`.

## Scope and limits

MVP is portfolio-level. Per-account, per-strategic-bucket, and benchmark
attribution have shipped on `totals.by_account` / `totals.by_strategic_bucket`
bookends; CLI surfacing follows.

> Caveat: today's FX lock is applied to all historical cashflows. Per-cashflow
> FX provenance lands with the `Money.fx_ref` rollout (schema 1.5.0 onward).

## See also

- [Compute portfolio TWR / MWR](../how-to/compute-performance.md)
- [Performance methodology](../explanation/performance-methodology.md)
