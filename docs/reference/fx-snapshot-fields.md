# FX Snapshot Fields

Every snapshot row written by `rikdom snapshot` carries a `metadata.fx_lock`
block recording the conversion context used to compute base-currency totals.
This page documents the fields. For the operational recipe see
[work with multi-currency holdings](../how-to/work-with-multi-currency.md);
for the rationale see
[multi-currency engine](../explanation/multi-currency-engine.md).

## `metadata.fx_lock`

| Field | Type | Description |
| --- | --- | --- |
| `rates_to_base` | `{currency: number}` | Rate used to convert each foreign currency to `base_currency`. |
| `rate_dates` | `{currency: ISO-8601 date}` | Date the rate was observed in `fx_rates.jsonl`. |
| `sources` | `{currency: string}` | Provenance label for each rate (e.g. provider name). |

## FX history file

`data/fx_rates.jsonl` is append-only JSONL, one rate per line:

```json
{"as_of_date": "2026-04-30", "base_currency": "BRL", "quote_currency": "USD", "rate_to_base": 5.21, "source": "ecb"}
```

The same shape is referenced by `Money.fx_ref` (schema 1.5.0+) for
line-item FX provenance on activities and holdings.

## Resolution order

For a holding or activity in currency `CCY`:

1. `fx_rates_to_base[CCY]` from the snapshot FX lock.
2. `metadata.fx_rate_to_base` on the record itself (compatibility fallback,
   emits `TRUST_FX_FALLBACK_USED`).
3. None resolves → emit `RECON_FX_MISSING`; record excluded from totals
   (or raised as error in strict mode).

## See also

- [Work with multi-currency holdings](../how-to/work-with-multi-currency.md)
- [Multi-currency engine](../explanation/multi-currency-engine.md)
- [Reconciliation codes reference](reconciliation-codes.md)
