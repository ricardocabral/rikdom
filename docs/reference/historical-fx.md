# Historical cashflow FX

`rikdom.historical_fx` resolves dated, directional exchange rates from the
[local market-series contract](market-series.md). It reads local files and
performs no provider calls, current-rate acquisition, or canonical writes.

## Local configuration

`load_historical_fx(path: str | Path, *, base_currency: str) -> HistoricalFx`
loads a configuration file and its referenced market-series file.

```json
{
  "contract_version": "1.0",
  "market_series_file": "market-series.json",
  "series_by_currency": {"USD": "example-fx"},
  "max_age_seconds": 86400,
  "retrieved_before": null
}
```

Every field is required. Unknown fields, duplicate JSON keys, nonfinite JSON
constants, and other contract versions are rejected. `market_series_file` is
a nonblank local path; relative paths resolve from the configuration file's
directory. Absolute paths are accepted. `base_currency` comes from the caller
and is not a configuration field.

## Resolver API

```python
HistoricalFx(
    series: MarketSeries,
    *,
    base_currency: str,
    series_by_currency: dict[str, str],
    max_age_seconds: float,
    retrieved_before: str | None = None,
)
```

| Parameter | Contract |
| --- | --- |
| `series` | Validated `MarketSeries`, normally from `load_market_series`. |
| `base_currency` | Reporting currency, three uppercase letters. Exposed as `HistoricalFx.base_currency`. |
| `series_by_currency` | Explicit native currency to nonblank series ID mapping. Currency keys use three uppercase letters. |
| `max_age_seconds` | Finite nonnegative number; booleans are invalid. Age is measured from effective time, inclusive at the limit. |
| `retrieved_before` | Optional inclusive knowledge cutoff, an explicit UTC timestamp ending in `Z` or `+00:00`. `None` uses every revision in the file. |

Invalid constructor configuration raises `ValueError` immediately.

`resolve(currency: str, when: datetime) -> FxRateResult` accepts a three-letter
uppercase native currency and a timezone-aware datetime. It normalizes the
request instant to UTC. Invalid codes and naive datetimes raise `ValueError`.

A selected rate multiplies the native amount into the reporting currency.
Native currency equal to reporting currency returns an available identity
rate of `1.0`, without requiring a mapped series. A foreign currency selects
only its explicitly mapped `kind: fx` series, whose `currency_pair.base`
matches the native currency and `currency_pair.quote` matches the reporting
currency. The resolver performs no inversion, triangulation, or alternative
series selection.

### Result and provenance

`FxRateResult` is a frozen dataclass with these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `rate` | `float \| None` | Finite positive multiplier, or `None` when unavailable. |
| `status` | `str` | `available`, `missing`, or `stale`. |
| `reason` | `str \| None` | Unavailability reason, or `None`. |
| `evidence` | `dict[str, Any]` | Requested UTC `as_of`, requested `currency_pair`, age limit, retrieval cutoff, status, reason, and selected rate. |

Mapped lookups also retain `series_id`, `age_seconds`, complete series
metadata including license, the selected observation including effective and
retrieval timestamps/source/revision identity, and `superseded` observations.
Stale results keep their selected observation as evidence but expose no rate.
Missing mappings use `missing_currency_mapping`; incompatible kinds or pairs
use `incompatible_currency_pair`. Other missing and stale reasons follow the
market-series lookup contract. Identity results set `identity: true`.

## Performance API and output

The following functions accept optional `historical_fx: HistoricalFx | None = None`:

- `compute_performance`
- `compute_performance_by_account`
- `compute_performance_by_strategic_bucket`
- `extract_external_cashflows`

The resolver's reporting currency must equal the function's `base_currency`;
a mismatch raises `ValueError`. Omission preserves legacy undated conversion
behavior. In historical mode, posted external cashflows use the selected
effective activity timestamp after correction projection. Cancelled,
superseded, and out-of-window events do not contribute conversions. Missing
or invalid timestamps are unresolved events because their period cannot be
verified.

Historical conversion never falls back to `fx_rates_to_base` or activity
metadata. Missing, stale, incompatible, malformed, or overflowing conversion
inputs make the affected portfolio/account/bucket Modified Dietz, selected
TWR, XIRR, and net external flow total unavailable. Other accounts and buckets
remain usable. Aggregation overflow also makes affected totals and returns
unavailable. Cashflow counts count successfully converted events; the evidence
and warnings retain unresolved events. The extractor retains its existing
`(cashflows, warnings)` result shape; callers must inspect warnings for
incomplete conversions.

Portfolio and scoped results expose:

| Field | Values |
| --- | --- |
| `fx_status` | `complete` when all eligible dated conversions and their aggregate are available; `unavailable` when affected conversion data is incomplete; `legacy_approximate` when the resolver is omitted. A portfolio without usable bookends reports `unavailable` in historical mode. |
| `fx_evidence` | One dictionary per effective eligible external activity, including `activity_id`, `event_type`, `effective_at`, finite `native_amount`, `native_currency`, signed converted `amount_base` where available, and resolver provenance. `lookup_status` retains the original available/missing/stale lookup status separately from conversion `status`. Invalid diagnostic values are represented by `None`. |

Complete dated conversions permit portfolio linked TWR when explicit
before/after flow valuations satisfy the existing linking prerequisites.
Account and strategic bucket returns retain Modified Dietz attribution.
Unresolved internal-transfer identity remains disclosed and approximate.
Instrument native returns are unchanged. Historical benchmark comparisons
receive the selected portfolio TWR; legacy comparisons receive legacy Dietz.

`fx_status: complete` certifies only the cashflow conversions used here.
Snapshot bookend values and before/after flow valuations are independently
supplied reporting-currency inputs. Historical cashflow FX does not recompute
or certify their valuation FX, price provenance, or economic completeness.
