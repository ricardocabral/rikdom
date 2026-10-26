# frankfurter

Optional Pluggy `external/connector` plugin using API `1.1` and the existing
`connector_describe` / `connector_query` hooks. Frankfurter's HTTP endpoint,
request construction, and response validation live in this plugin. Core FX
history selection has no provider default.

## Query

From the repository root:

```bash
uv run rikdom connector describe --plugin frankfurter --plugins-dir plugins
uv run rikdom connector query --plugin frankfurter --operation daily-rates \
  --params '{"base_currency":"BRL","quote_currencies":["USD","EUR"],"as_of_date":"2026-04-19"}' \
  --plugins-dir plugins
```

Description is offline. Query explicitly requests network acquisition and prints
a result; it does not write portfolio or FX history files. This plugin needs no
credentials or additional Python dependencies.

`daily-rates` requires a three-letter `base_currency`, a nonempty list of
`quote_currencies` different from the base, and a valid `YYYY-MM-DD` `as_of_date`.
Currency codes are normalized to uppercase. Each quote makes one fixed-host
HTTPS request with a ten-second timeout. Unsupported parameters and malformed
requests fail before transport. HTTP, connectivity, and invalid-response errors
raise `FrankfurterError`; there are no automatic retries.

## Rate and provenance contract

The query hook returns a currency-keyed object, for example:

```json
{"USD":{"rate_to_base":5.2,"as_of_date":"2026-04-17","source":"frankfurter"}}
```

`rate_to_base` converts one unit of the quote currency into the requested base.
The effective date comes from the provider response. A Sunday request can use
Friday's rate; the plugin keeps Friday's date. Future dates, nonpositive or
nonfinite rates, missing dates, and mismatched provider base/amount are rejected.
The CLI's generic connector envelope places this object under `data`.

Core callers can explicitly opt into missing-rate acquisition by passing
`auto_ingest=True` and a callable to `ensure_snapshot_fx_lock`. The callable
accepts keyword arguments `base_currency`, `quote_currencies`, and `as_of_date`
and can dispatch them to this plugin's `daily-rates` operation. The returned
entries are appended to FX history with their effective dates and source.
Without both opt-in and a callable, core reads cached history only.

## Offline verification

Contract fixtures cover detached description output and invalid query input.
Successful queries and provider failures are tested with only HTTP transport
mocked; the plugin parsing, normalization, and core history integration run
normally. Tests do not contact Frankfurter.

```bash
uv run python -m unittest discover -s tests -p test_frankfurter.py -v
uv run python -m unittest discover -s tests -p test_plugin_contracts.py -v
```
