# Compute portfolio TWR / MWR

Use this guide to compute time-weighted return (linked TWR or a disclosed Dietz approximation) and
money-weighted return (XIRR) over a window. For the JSON schema of the
output, see [performance output reference](../reference/performance-output.md).
For the math behind the numbers, see
[performance methodology](../explanation/performance-methodology.md).

## Default window

```bash
make performance
```

Defaults: `--since` falls back to the earliest snapshot, `--until` to the
most recent.

## Custom window

```bash
uv run rikdom performance \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --since 2026-01-01 \
  --until 2026-12-31
```

`--since` and `--until` accept `YYYY-MM-DD`. The reported `period_start` is
the timestamp of the chosen start snapshot; the reported `period_end` is the
timestamp of the chosen end snapshot — see
[bookend selection](../reference/performance-output.md#bookend-snapshot-selection).

## Supply explicit before/after cashflow valuations

Create a version 1 evidence file using the
[flow valuation contract](../reference/performance-output.md#explicit-cashflow-valuation-evidence),
then run:

```bash
uv run rikdom performance --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl --flow-valuations data/flow-valuations.json
```

Use portfolio valuations immediately before and after each external cashflow
instant, in the portfolio base currency, with an identified source and declared
rounding tolerance. Supply one row for all flows at the same instant. Do not
rename daily snapshots as before/after evidence. Check `twr_method` and
`twr_fallback_reason`: `twr_return_pct` is the selected period return, while
`twr_pct` remains the legacy Dietz estimate and `mwr_pct` remains annualized
XIRR. Sidecars support portfolio scope only. Missing boundaries, undated FX and
unresolved transfers remain visibly approximate.

## Replay dated FX for cashflows and benchmarks

Supply an explicit local [historical FX configuration](../reference/historical-fx.md)
to convert each contribution or withdrawal at its activity date:

```bash
uv run rikdom performance \
  --portfolio data-sample/performance-fx/portfolio.json \
  --snapshots data-sample/performance-fx/snapshots.jsonl \
  --historical-fx data-sample/performance-fx/historical-fx.json \
  --flow-valuations data-sample/performance-fx/flow-valuations.json
```

This synthetic example converts a USD 10 contribution using 5 BRL/USD on the
activity date: net contributions are BRL 50. Independent flow valuations of
110 before and 160 after the contribution, with opening 100 and closing 176,
produce linked TWR of 21%: `(110 / 100) × (176 / 160) − 1`.
The later 6 BRL/USD observation does not change the earlier contribution.

The command reads local files and does not acquire data or modify the ledger.
`fx_status` and `fx_evidence` disclose the requested date, selected observation,
source and corrections. A missing or stale required rate makes affected returns
and contribution totals unavailable; current FX and activity metadata are never
substituted in this mode. Without `--historical-fx`, legacy approximation behavior
continues. Instrument mode already reports native-currency returns and rejects
this option.

With `--policy` and `--benchmarks-dir`, the same resolver converts benchmark
bookends before comparison or composite blending. See [benchmark FX rules](../reference/benchmark-fx.md)
for exact-window, source and return-convention requirements. Price-only or
unknown-convention series cannot establish comparable excess return. Independent
snapshot values remain caller-supplied: dated cashflow conversion does not prove
that snapshot valuations used historical prices or FX.

## Library use

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
    flow_valuations=None,  # parsed JSON object with the explicit version 1 contract
)
print(result.twr_return_pct, result.twr_method, result.mwr_pct)
```

`modified_dietz`, `xirr`, and `extract_external_cashflows` are also exported
for callers that already have base-converted cashflows.

## Return since an instrument's acquisitions

Use the dated activity ledger to include purchases, sales, distributions,
amortizations, reported fees and taxes for one holding:

```bash
uv run rikdom performance --data-dir data --by instrument --instrument AAAA11
```

`--instrument` accepts a ticker or a holding ID. When several active holdings
share a ticker, select their individual IDs. Omit it to inspect invested and
activity-bearing holdings. This mode does not require portfolio snapshots or
apply today's FX rate to historical transactions.

The calculation uses `settled_at` when reported, otherwise `effective_at`.
It requires an explicit complete-history declaration under
`holding.extensions.rikdom_instrument_history`, including coverage dates.
Unknown, partial, inconsistent or ambiguous history produces
`status: incomplete_history`, with `profit_amount` and `xirr_pct` set to
`null`. Observed receipts and costs remain available for reconciliation.
Corrections are resolved before calculating returns. A distribution with unknown amount basis
prevents a complete return; a net-marked receipt is not charged twice. See the
[income amount-basis contract](../reference/cli.md#income). Do not declare
completeness from a current position or annual income total.

The default terminal value is the holding's market value at its actual
`as_of` timestamp. To supply a separately calculated liquidation value:

```bash
uv run rikdom performance --data-dir data --by instrument --instrument AAAA11 \
  --until 2025-12-31 --terminal-value 1000.00
```

Replace the example ticker, date and amount with your instrument's values.
The amount is illustrative, in the instrument's transaction currency. Supply
net proceeds only after separately determining sale costs and taxes. The
calculator does not infer them. A stale position value is never relabeled as
today's value. `--since` is unsupported in instrument mode because an arbitrary
start date needs a historical opening valuation.

Portfolio policy benchmark returns are not applied in this mode. An actual
Tesouro IPCA+ or CDB comparison requires a separate product simulation using
the same investment dates, a selected maturity, historical prices or contracted
rates, cash withdrawal/reinvestment assumptions, fees and applicable taxes.
An index-level return is not that product simulation.

See [FII history conventions](../reference/fii-history.md) for imports,
corporate actions and benchmark input storage.

## See also

- [Performance output reference](../reference/performance-output.md)
- [Performance methodology](../explanation/performance-methodology.md)
- [Work with multi-currency holdings](work-with-multi-currency.md) — FX resolution affects cashflow conversion.
