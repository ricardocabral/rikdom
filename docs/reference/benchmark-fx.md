# Historical benchmark FX

`resolve_benchmarks_for_targets(..., historical_fx=resolver)` translates each
benchmark bookend into the portfolio reporting currency using
`resolver.resolve(currency, actual_bookend_datetime)`. Rates multiply native
levels. The resolver reporting currency must match the portfolio base currency.
The window must increase and use timezone-aware datetimes.

For example, a USD benchmark rising from 100 to 110 with BRL-per-USD rates of
5 and 6 has a BRL return of `110 * 6 / (100 * 5) - 1 = 32%`. Its native return
remains 10%. Missing, stale, or incompatible FX makes the translated return
unavailable. Historical mode never substitutes current rates or metadata rates.

## Benchmark input

Existing JSONL rows remain supported. Two optional fields establish the
comparison convention and source:

```json
{"as_of":"2026-01-31T23:59:59Z","level":100,"currency":"USD","return_convention":"total_return","source":"synthetic-total-return-index"}
{"as_of":"2026-04-30T23:59:59Z","level":110,"currency":"USD","return_convention":"total_return","source":"synthetic-total-return-index"}
```

`return_convention` defaults to `unspecified`; `source` defaults to `null`.
Historical mode can display a translated return with unspecified convention or
source, but cannot report excess for it. A price index can be labeled
`price_return`; it cannot support a total-return excess comparison.

The loader skips invalid or nonpositive levels, including booleans and
nonfinite numbers. Historical calculation also validates directly supplied
points. Duplicate timestamps are ambiguous and make a series unavailable;
benchmark rows have no revision-selection contract. Select one benchmark
vintage before loading it. FX revision selection belongs to the supplied
historical FX resolver, and its evidence is retained.

Date-only `as_of` values retain their established end-of-day UTC meaning
(`23:59:59+00:00`). Timestamps with an explicit timezone are converted to UTC.
For compatibility, legacy mode interprets timezone-naive timestamps as UTC;
`BenchmarkPoint.as_of_timezone_assumed` records this assumption and historical
mode rejects such series. Directly supplied timezone-naive points are also
rejected. Use explicit offsets for intraday data.

## Comparability and output

Historical comparisons add these fields:

| Field | Meaning |
| --- | --- |
| `currency`, `twr_pct` | Reporting currency and translated return in percent |
| `native_currency`, `native_twr_pct` | Original single-series currency and return; `null` for composites |
| `return_convention` | Bookends' common convention, otherwise `unspecified` |
| `fx_evidence` | Each bookend's requested date, rate, status, reason, and resolver evidence |
| `data_provenance` | Each actual bookend's date, level, currency, convention, and source |
| `comparison_status` | `comparable`, `not_comparable`, or `unavailable` |

A single-series result reports its actual selected dates in `period_start`
and `period_end`. A composite retains the requested window; its component
results and provenance disclose their actual dates. Resolver evidence retains
FX effective/retrieval dates, revisions, source, and license when supplied by
the resolver. Invalid nonfinite levels are represented as `null` in provenance.

Excess is `portfolio_return_pct - benchmark_return_pct`, in percentage points.
It requires an available finite portfolio return, exact portfolio bookend
timestamps, consistent `total_return` conventions, and a nonblank source at
both benchmark bookends. A prior or partial benchmark window may have a
translated return, but its status is `not_comparable` and excess is `null`.
The comparison explicitly assumes portfolio snapshot valuations represent
total-return performance. Historical cashflow FX does not certify snapshot
valuation FX or independently establish that return convention.

`comparable` describes the benchmark's eligibility: excess remains `null` when
the portfolio return is unavailable. `unavailable` means the translated
benchmark return itself could not be calculated.

## Composites

Every positive-weight component is translated into the reporting currency
before its return is blended. For example, 60% of a 10% BRL return and 40% of
the 32% translated return above gives 18.8%. Native returns in different
currencies are never blended and labeled as a reporting-currency return in
historical mode.

Weights must be finite nonnegative numbers, excluding booleans, and total
100% within an absolute tolerance of `1e-6` percentage points. Every declared
component must have a valid reference and weight. A valid zero-weight
component can be ignored even when its data is unavailable. If any
positive-weight component is unavailable, the entire composite return is
unavailable: there is no partial blend or renormalization. Excess additionally
requires every active component to be comparable. Cycles are unavailable.

Without `historical_fx`, existing native-return and legacy composite behavior
is preserved, with finite-number safeguards. Its `comparison_status` is
`legacy`; the stronger historical comparability rules do not apply.
