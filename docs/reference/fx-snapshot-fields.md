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
| `rate_dates` | `{currency: ISO-8601 date}` | Actual effective date of the selected rate in `fx_rates.jsonl`. |
| `sources` | `{currency: string}` | Original history or acquisition source (e.g. provider name); `history` for legacy cached rows without a source. |

## FX history file

`data/fx_rates.jsonl` is append-only JSONL, one rate per line:

```json
{"as_of_date": "2026-04-30", "base_currency": "BRL", "quote_currency": "USD", "rate_to_base": 5.21, "source": "ecb"}
```

The same shape is referenced by `Money.fx_ref` (schema 1.5.0+) for
line-item FX provenance on activities and holdings.

## Acquisition boundary

Core selects the latest cached rate on or before the snapshot date. It does not
select a provider or make HTTP requests. `ensure_snapshot_fx_lock` defaults to
`auto_ingest=False`; acquisition requires both `auto_ingest=True` and an
explicitly injected fetcher.

The fetcher receives keyword arguments `base_currency`, `quote_currencies`, and
`as_of_date`, and returns entries keyed by quote currency:

```json
{"USD":{"rate_to_base":5.21,"as_of_date":"2026-04-30","source":"custom-provider"}}
```

Core retains the supplied effective date and source in both history and the
snapshot lock. A response without a valid effective date, or with a future date
or nonpositive/nonfinite rate, is ignored and produces a missing-rate warning.
Legacy numeric entries such as `{"USD":5.21}` remain supported for injected
fetchers; their date is the requested date and their source is the generic
`auto_ingest`. New integrations should supply dated entries.

The optional [Frankfurter connector](../../plugins/frankfurter/README.md)
implements this dated contract through the existing `daily-rates` query operation.
It preserves the provider's actual effective date, including weekends and
holidays, rather than labeling it with the requested date.

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
