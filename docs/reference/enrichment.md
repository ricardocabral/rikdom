# Normalized enrichment contract

`enrichment(ctx, request)` is an Experimental first-result hook in plugin API
`1.2`. `run_enrichment_pipeline(plugin_name, plugins_dir, request) -> dict`
validates the request before loading the provider, detaches JSON at both
boundaries, validates the entire returned MarketSeries document, and derives
historical lookups in the host. It does not write portfolio or ledger files.

API `1.0` and `1.1` hooks retain their contracts. A provider implementing this
hook must declare `api_version: "1.2"` and `plugin_types: ["enrichment"]`.
API `1.2` may also declare the existing connector or stable plugin types.
Manifest API, enrichment payload, and MarketSeries versions are separate.

## Request

The envelope contains exactly these fields:

```json
{
  "contract_version": "1.0",
  "source": {"path": "plugins/local-market-series/fixtures/sample/input.json"},
  "lookups": [{
    "series_id": "br-price",
    "as_of": "2026-01-02T00:00:00Z",
    "max_age_seconds": 0,
    "retrieved_before": "2026-01-02T00:00:00Z"
  }]
}
```

| Field | Contract |
| --- | --- |
| `contract_version` | Required string `"1.0"`. Other versions are rejected. |
| `source` | Required strict JSON object interpreted by the selected provider. The reference provider accepts only an explicit, non-empty `path`. Relative paths resolve against process CWD. |
| `lookups` | Required array, possibly empty. Each item has exactly `series_id`, `as_of`, `max_age_seconds`, and optional `retrieved_before`. |
| `series_id` | Non-blank exact identifier; no symbol inference or provider fallback. |
| `as_of` | Explicit UTC timestamp (`Z` or `+00:00`). |
| `max_age_seconds` | Finite nonnegative number. Booleans are rejected. |
| `retrieved_before` | Optional inclusive UTC knowledge cutoff; omitted or `null` considers all supplied revisions. |

All queries are validated before provider execution, including queries for
unknown series. Unknown envelope/query fields, non-string JSON keys, cycles,
NaN, Infinity, tuples and arbitrary Python objects are rejected. Provider
mutation of the detached request cannot alter the caller or host's queries.

## Provider response

The hook returns exactly:

```json
{
  "contract_version": "1.0",
  "market_series": {"contract_version": "1.0", "series": []}
}
```

`market_series` is a complete [MarketSeries 1.0](market-series.md) document.
It retains instrument namespaces/identifiers, currencies, directional FX pairs,
adjustment convention, declared coverage, license, and observation source,
effective/retrieval timestamps and correction chains. Any invalid record
rejects the whole result. An empty series array is valid and produces missing
lookups; it does not assert market coverage.

The provider cannot supply computed lookups or overwrite host plugin identity.
Unsupported versions and extra response fields raise `PluginEngineError`.
`parse_market_series(document) -> MarketSeries` provides the same detached,
all-or-nothing in-memory validation as `load_market_series(path)`; invalid
documents raise `ValueError`.

## Pipeline result

The pipeline returns the validated document and host-derived lookups:

```text
{
  contract_version: "1.0",
  plugin: {name, version, api_version},
  market_series: <complete supplied MarketSeries 1.0 document>,
  lookups: [<MarketSeries LookupResult in request order>]
}
```

Lookups preserve selected metadata and superseded observations. The latest
eligible effective timestamp wins; the latest revision at or before the
knowledge cutoff wins within that timestamp. No future quote is selected.
An unknown series, absent eligible observation, or request outside declared
coverage returns `missing` with a reason. An observation older than the explicit
maximum returns `stale` with its evidence. Neither state silently succeeds or
falls back to another series. An exact maximum age remains available.

No run timestamp is added. The same file, request and plugin version produce
identical JSON, including missing/stale diagnostics. Retrieval evidence comes
from supplied observations; opening the cache does not invent a retrieval date.
The returned document and lookup evidence are independent copies.

## Local reference and limits

`local-market-series` reads one explicit user-maintained or previously cached
JSON file. Duplicate JSON keys, invalid JSON and non-finite constants are
rejected before normalization. It has no HTTP client, credential discovery,
cache refresh, network fallback, portfolio mutation, or automatic symbol mapping.
Trusted Python plugins still have process access; this contract is not a sandbox.

Committed fixtures cover synthetic BR (`BVMF`/BRL), US (`XNAS`/USD), and Japan
(`XTKS`/JPY) identifiers, plus directional USD/JPY FX. They prove neutral
normalization and replay only. They provide no live market coverage, exchange
calendars, holiday rules, licensed commercial data, corporate action processing,
or automatic cross-rate/inverse FX synthesis. Actual data use remains subject
to its supplied license and source evidence.

## Contract fixtures and SDK

An enrichment `case.json` supplies `hook: "enrichment"` and `request` with the
shape above. `source.path` is resolved relative to the case directory by the
contract runner. The runner invokes the real pipeline, validates malformed
responses, compares `expected.json`, and verifies deterministic reruns. Invalid
cases use `expected_error.json`. The existing dedicated plugin-contract CI job
covers this hook and requires a fixture for every declared implementation.

The bundled `template-enrichment` resource includes a manifest, working
file-only provider, synthetic input, `case.json`, expected result, and an
executable runtime unittest. `rikdom plugin init NAME --type enrichment`
selects this resource; the default remains `source/input`.
