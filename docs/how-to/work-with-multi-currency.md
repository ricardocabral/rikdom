# Work with multi-currency holdings

Use this guide to drive the snapshot and aggregation flow when your
portfolio holds non-base-currency assets. For the conceptual model, see
[multi-currency engine](../explanation/multi-currency-engine.md). For the
fields written into each snapshot row, see
[FX snapshot fields reference](../reference/fx-snapshot-fields.md).

## Default flow

```bash
uv run rikdom snapshot --portfolio data/portfolio.json --snapshots data/snapshots.jsonl
```

By default, this reads local `data/fx_rates.jsonl` and writes a row with
`metadata.fx_lock`. It makes no provider request. Missing rates can use a
legacy per-holding fallback; otherwise affected values are excluded with
warnings. Add `--strict-quality` to reject valuation quality errors before
appending a snapshot.

## Explicitly acquire missing FX rates

Select an installed connector that implements `daily-rates`, for example:

```bash
uv run rikdom snapshot --fx-provider frankfurter --plugins-dir plugins
```

This appends acquired rates to `data/fx_rates.jsonl` before valuation. See
the [Frankfurter plugin](../../plugins/frankfurter/README.md) for supported
currencies and provider configuration. `--no-fx-auto-ingest` disables
acquisition even when `--fx-provider` is supplied; it does not itself make
missing FX fatal.

## Use a custom FX history file

```bash
uv run rikdom snapshot --fx-history data/custom_fx_rates.jsonl
```

## Compatibility fallback

If a holding still carries `metadata.fx_rate_to_base`, rikdom uses it as a
compatibility fallback and emits a warning so you can migrate progressively
to history-driven FX. Inspect warnings via `rikdom validate` and the
[reconciliation codes reference](../reference/reconciliation-codes.md)
(`TRUST_FX_FALLBACK_USED`).

## See also

- [Multi-currency engine](../explanation/multi-currency-engine.md)
- [FX snapshot fields reference](../reference/fx-snapshot-fields.md)
- [Reconciliation codes reference](../reference/reconciliation-codes.md)
