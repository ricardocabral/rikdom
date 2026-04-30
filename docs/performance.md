# Performance Module

Compute portfolio-level **time-weighted return (TWR)** via Modified Dietz and
**money-weighted return (MWR)** via XIRR over a chosen window.

## Scope

MVP is portfolio-level. Per-account, per-strategic-bucket, and benchmark
attribution are deferred. See `docs/grounding-plan.md` Step 5 for the
follow-up plan.

## Input

- `data/portfolio.json` — for `settings.base_currency`, `activities[]`, and FX
  fallbacks (`metadata.fx_rate_to_base`).
- `data/snapshots.jsonl` — period-end portfolio values.
- `data/fx_rates.jsonl` (optional) — used to resolve foreign-currency
  cashflows to the base currency via the same fallback chain as `aggregate`.

## Output

A JSON object printed to stdout:

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

## Generate

```bash
make performance
```

Or directly, with an explicit window:

```bash
uv run rikdom performance \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --since 2026-01-01 \
  --until 2026-12-31
```

Defaults: `--since` falls back to the earliest snapshot, `--until` to the
most recent.

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

Activities without `status: posted` are skipped (matches `aggregate`).

## FX handling

Foreign-currency cashflows are converted to base currency using the same
fallback chain as `aggregate_portfolio`:

1. `fx_rates_to_base[CCY]` from the snapshot FX lock (loaded from
   `--fx-history`).
2. `metadata.fx_rate_to_base` on the activity itself.

If neither resolves, the cashflow is **skipped with a warning** rather than
blocking the whole computation; the resulting TWR/MWR is still emitted but
will be flagged as approximate via `warnings[]`.

> Caveat: today's FX lock is applied to all historical cashflows. Stamping
> per-cashflow FX provenance is tracked as Step 7 in the grounding plan.

## Method notes

**Modified Dietz** (TWR):

```
denom = start_value + Σ w_i · CF_i
TWR   = (end_value − start_value − Σ CF_i) / denom
where w_i = (period_end − cf_time) / (period_end − period_start)
```

**XIRR** (MWR): Newton's method with bisection fallback over `[-0.999999,
10.0]`, treating the start value as a negative cashflow at `period_start`,
each external cashflow with the investor-perspective sign flipped, and the
end value as a positive cashflow at `period_end`.

## Library API

The CLI is a thin wrapper around pure functions in
`src/rikdom/performance.py`:

```python
from rikdom.performance import compute_performance

result = compute_performance(
    snapshots,         # list of snapshot dicts
    activities,        # list of activity dicts
    base_currency="BRL",
    fx_rates_to_base={"USD": 5.25},
    since="2026-01-01",
    until=None,
)
print(result.twr_pct, result.mwr_pct)
```

Lower-level helpers (`modified_dietz`, `xirr`, `extract_external_cashflows`)
are also exported for callers that already have base-converted cashflows.
