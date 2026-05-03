# Compute portfolio TWR / MWR

Use this guide to compute time-weighted return (Modified Dietz) and
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
)
print(result.twr_pct, result.mwr_pct)
```

`modified_dietz`, `xirr`, and `extract_external_cashflows` are also exported
for callers that already have base-converted cashflows.

## See also

- [Performance output reference](../reference/performance-output.md)
- [Performance methodology](../explanation/performance-methodology.md)
- [Work with multi-currency holdings](work-with-multi-currency.md) — FX resolution affects cashflow conversion.
