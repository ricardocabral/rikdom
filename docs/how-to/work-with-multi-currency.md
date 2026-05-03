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

This auto-fetches missing FX rates, appends them to `data/fx_rates.jsonl`,
and writes a row with a deterministic `metadata.fx_lock`.

## Disable automatic FX ingestion

History-only mode — useful when you want imports to fail fast instead of
quietly fetching:

```bash
uv run rikdom snapshot --no-fx-auto-ingest
```

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
