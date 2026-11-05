# Local market series contract and replay

`rikdom market-series` reads one user-supplied JSON file and prints a historical
price or FX lookup as stable JSON. It uses no network, keys, account, current
clock, portfolio, or ledger. It never writes files. This bounded file/manual
fallback also supplies the [normalized enrichment hook](enrichment.md) and
[explicit historical valuation replay](historical-valuation.md). The replay
command itself does not modify the portfolio schema or canonical files.
Existing connectors return provider-native JSON; convert it explicitly to this
contract before replay. Local plugins remain trusted in-process Python.

## Version 1.0 input

See the complete sanitized [manual sample](../../data-sample/market-series.json).
Its invented prices and FX rates demonstrate replay, not market coverage. The
sample data is dedicated under CC0-1.0; provider data needs its own license.

The top-level object has exactly `contract_version: "1.0"` and `series`, an array.
An empty array is valid and every query then reports `unknown_series`. Every
series has exactly these fields, plus the identity appropriate to its kind:

| Field | Contract |
| --- | --- |
| `id` | Non-blank exact lookup identity, unique within the file. |
| `kind` | `price` or `fx`. |
| `instrument` | Price only: object with `namespace`, `id`, `currency`. Namespace and id are non-blank strings; use exchange + ticker, ISIN, or another explicit namespace. No cross-provider identity resolution is attempted. |
| `currency_pair` | FX only: object with distinct `base` and `quote` currencies. Value means **quote units per one base unit** (USD/BRL 5.25 means BRL 5.25 per USD 1). No automatic inversion or triangulation. |
| `currency` | Uppercase three-letter code; must match instrument currency or FX quote currency and every observation currency. Codes are checked syntactically, without an ISO registry lookup. |
| `adjustment` | Price: `unadjusted`, `split_adjusted`, or `total_return_adjusted`; FX: `not_applicable`. One convention applies to the entire series. No adjustment calculation is performed. |
| `coverage` | Object with inclusive UTC `start` and `end`; start <= end. Declares the supported effective-time query interval, not a promise of continuous observations. Queries outside return missing, never extrapolate. |
| `license` | Object with non-blank `name` and `uri`. The URI is declared metadata, never fetched or independently verified. No default provider license is assumed. |
| `observations` | Array, possibly empty; each observation has exactly the fields below. |

Every observation contains:

| Field | Contract |
| --- | --- |
| `id` | Non-blank identity, unique within its series. |
| `effective_at` | UTC timestamp within declared coverage: when the value applies. |
| `retrieved_at` | UTC timestamp at or after effective time: when this vintage was acquired or entered manually. |
| `source` | Non-blank provenance, e.g. `manual:example` or a provider identifier. |
| `value` | Positive finite JSON number. Booleans, strings, NaN, infinity and values outside finite float range are rejected. Original numeric JSON values are retained in output. |
| `currency` | Must equal the series currency. |
| `supersedes` | `null` for an original observation, otherwise the id of the immediately previous vintage. |

All timestamps require a real calendar date, seconds, and explicit UTC (`Z` or
`+00:00`); optional fractional seconds have 1–6 digits. Date-only, naive and
non-UTC timestamps are rejected. Output normalizes timestamps to `Z`. Non-blank
strings cannot have surrounding whitespace. Unknown versions, extra/missing
fields, duplicate JSON keys, duplicate series/observation ids, malformed numbers
and any invalid observation reject the entire file with a diagnostic. Nothing
is silently dropped or coerced.

## Corrections and historical knowledge

At each effective timestamp there is exactly one original observation. Later
vintages must explicitly reference the prior observation through `supersedes`,
keep the same effective timestamp, and have strictly increasing retrieval times.
Missing references, two roots, self references, cycles, forks, and identical
unlinked duplicates are invalid. All vintages stay in the input. File order has
no meaning; conflicting revisions never win by appearing last.

Lookup first filters to effective time <= `--as-of` and, if supplied, retrieval
time <= `--retrieved-before`. It then selects the latest effective timestamp,
then the latest eligible vintage for that timestamp. Both comparisons are
inclusive. A later correction of an older effective observation cannot displace
a newer effective observation. `superseded` in the result lists earlier eligible
vintages of the selected observation, oldest first.

Without `--retrieved-before`, replay uses all knowledge in the file, including
corrections acquired after the historical as-of. Supply that cutoff to reproduce
what was known at a historical instant. These are distinct time dimensions:
as-of controls market time; retrieved-before controls knowledge time.

## CLI recipe

From a checkout with dependencies installed, these commands need no paid service
or network. Repeat the first command to get the same JSON and provenance:

```bash
uv run rikdom market-series --input data-sample/market-series.json \
  --series example-price --as-of 2026-01-03T16:00:00Z --max-age-seconds 86400

# Original vintage (100), before the correction was acquired:
uv run rikdom market-series --input data-sample/market-series.json \
  --series example-price --as-of 2026-01-03T16:00:00Z --max-age-seconds 86400 \
  --retrieved-before 2026-01-02T17:00:00Z

# FX quote 5.25 BRL per USD, available at an age of one day:
uv run rikdom market-series --input data-sample/market-series.json \
  --series example-fx --as-of 2026-01-03T16:00:00Z --max-age-seconds 86400

# Stale (172800 seconds old); retains the selected observation for inspection:
uv run rikdom market-series --input data-sample/market-series.json \
  --series example-price --as-of 2026-01-04T16:00:00Z --max-age-seconds 86400

# Missing: no effective observation yet, with no future-price fallback:
uv run rikdom market-series --input data-sample/market-series.json \
  --series example-price --as-of 2026-01-01T00:00:00Z --max-age-seconds 86400
```

`--input`, `--series`, `--as-of` and `--max-age-seconds` are mandatory. Maximum
age is a finite nonnegative number of seconds, inclusive; zero requires an
exact effective timestamp. Age uses effective time, never retrieval time or today.

Results include `status`, `reason`, query parameters, `age_seconds`, `series`
metadata (identity, currency, adjustment, coverage, license), the selected
`observation` (including effective/retrieved/source), and `superseded` provenance.
`available` has a null reason; `stale` has `maximum_age_exceeded`. `missing` uses
`unknown_series`, `outside_declared_coverage`, or `no_eligible_observation` and
has null observation/age. Successful lookups, including missing/stale, exit 0;
invalid files or queries exit 1 with stderr and no JSON; argument errors exit 2.
Consumers must check status before using a value. There are no output artifacts
or implicit workspace sample files.

## Python recipe

```python
from rikdom.market_series import load_market_series

store = load_market_series("data-sample/market-series.json")
query = dict(as_of="2026-01-03T16:00:00Z", max_age_seconds=86400)
result = store.lookup("example-price", **query)
assert result["status"] == "available"
assert result["observation"]["value"] == 101
assert result["superseded"][0]["value"] == 100
assert result == store.lookup("example-price", **query)
original = store.lookup("example-price", **query,
                        retrieved_before="2026-01-02T17:00:00Z")
assert original["observation"]["value"] == 100
```

The store validates once and returns detached JSON objects. Editing a returned
result cannot change subsequent lookups. It never modifies the supplied file or
canonical portfolio/activities. Source/license declarations are not independent
authenticity checks; this contract neither enforces redistribution rights nor
promises exchange calendars, regional provider coverage, split processing, live
acquisition, credential handling or scheduling.
