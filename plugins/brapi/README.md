# brapi

Pluggy `external/connector` plugin for the BrAPI v2 REST API. It exposes market
data through the Experimental `connector_describe` and `connector_query` hooks
in plugin API `1.1`. Existing API `1.0` plugins remain unchanged. Core contains
no BrAPI-specific commands or credentials.

For the shared discovery and query workflow, see
[query external data](../../docs/how-to/query-external-data.md). For implementing
another REST or MCP provider, see the [connector contract](../../docs/reference/plugin-hooks.md#connector-hooks).

## Run

From the repository root:

```bash
uv run rikdom connector describe --plugin brapi --plugins-dir plugins
uv run rikdom connector query --plugin brapi --operation quote \
  --params '{"symbols":["PETR4","VALE3"]}' --plugins-dir plugins
```

`--params` must be a JSON object. `symbols` accepts a list of strings or a
comma-separated string. Other parameter names use the API's camelCase spelling;
consult `describe` and the official OpenAPI for supported parameters.
The operation's `parameters` list includes the required `symbols` input;
`symbolParameter` records the API's query name (`symbols` or `currency`).

## Authentication and limits

Set `BRAPI_TOKEN` in the environment for authenticated requests. The plugin
sends it only as an `Authorization: Bearer …` header. Do not place a token in
the manifest, `--params`, URLs, or fixture files. Public demo symbols can be
queried without a token; other symbols and operations depend on authentication
and the provider's plan.

A `401` response identifies missing or invalid credentials; check `BRAPI_TOKEN`.
A `403` response indicates access denied by the provider, including plan
restrictions. Check the operation's availability in your BrAPI plan.

On `429`, the plugin honors `Retry-After` as seconds or an HTTP date. It makes
at most two automatic retries, each with a wait of at most 60 seconds. A larger
delay is returned as a `retry_after` hint without retrying early.

## Operations

| Operation | BrAPI endpoint |
| --- | --- |
| `quote` | `/api/v2/stocks/quote` |
| `historical` | `/api/v2/stocks/historical` |
| `dividends` | `/api/v2/stocks/dividends` |
| `fii-indicators` | `/api/v2/fii/indicators` |
| `fii-historical` | `/api/v2/fii/historical` |
| `fii-dividends` | `/api/v2/fii/dividends` |
| `currency` | `/api/v2/currency` |
| `currency-historical` | `/api/v2/currency/historical` |
| `macro` | `/api/v2/macro` |
| `macro-latest` | `/api/v2/macro/latest` |

Currency operations accept the connector's `symbols` input and map it to the
provider's `currency` query parameter inside this plugin. Operations and their
parameter handling are provider-specific; core passes them through unchanged.
Transport uses Python's standard-library `urllib.request`.

Copyable examples for each data category:

```bash
uv run rikdom connector query --plugin brapi --operation historical \
  --params '{"symbols":["PETR4","VALE3"],"range":"1mo","interval":"1d"}' --plugins-dir plugins
uv run rikdom connector query --plugin brapi --operation dividends \
  --params '{"symbols":["PETR4","VALE3"]}' --plugins-dir plugins
uv run rikdom connector query --plugin brapi --operation fii-indicators \
  --params '{"symbols":["MXRF11","HGLG11"]}' --plugins-dir plugins
uv run rikdom connector query --plugin brapi --operation fii-dividends \
  --params '{"symbols":["MXRF11","HGLG11"]}' --plugins-dir plugins
uv run rikdom connector query --plugin brapi --operation currency \
  --params '{"symbols":["USD-BRL","EUR-BRL"]}' --plugins-dir plugins
uv run rikdom connector query --plugin brapi --operation macro \
  --params '{"symbols":["selic","ipca"]}' --plugins-dir plugins
uv run rikdom connector query --plugin brapi --operation macro-latest \
  --params '{"symbols":["selic","ipca"]}' --plugins-dir plugins
```

## Result meaning

Results retain BrAPI's JSON shape, including `null`, errors, and warnings.
The CLI wraps these fields under `data`, with the host's retrieval timestamp,
operation, plugin version, API version, and connector contract version. The
query hook itself returns the original provider object. Request parameters and
credentials are not added to this provenance envelope.
Missing prices or indicators stay unknown; `null` is not converted to zero.
Quotes, dividends, and FII data are market observations, not broker statements
or proof of cash received. This plugin provides no account balances.

A `404` response means the provider found no data for the request. Batch
responses can omit unavailable symbols; the plugin preserves those responses
as returned. Callers must compare requested symbols with returned symbols
before treating a batch as complete.

For quotes, inspect `data.results` in the CLI envelope, then each result's
`symbol` and `data.regularMarketPrice`. The provider's `regularMarketTime`
records the quote time; the host's `retrievedAt` records acquisition time.

To save a quote response locally:

```bash
mkdir -p out
uv run rikdom connector query --plugin brapi --operation quote \
  --params '{"symbols":["PETR4","VALE3"]}' --plugins-dir plugins \
  > out/brapi-quote.json
```

This file is a saved response, not an automatic cache or replay facility.

Queries do not import ledger events, change canonical portfolio files, or
replace the existing FX provider. Normalized enrichment, cached replay,
permission enforcement, and sandboxing are outside this first query boundary.
The generic connector contract can also host MCP clients, but this plugin uses
REST and no concrete MCP transport is included.

## Verification

Contract fixtures are deterministic and offline: description has a saved
expected result, and query uses an unsupported operation with an expected
error. There is no response replay path. Successful responses and transport
behavior use HTTP-boundary mocks and do not require a token or paid API access.

```bash
uv run python -m unittest tests.test_plugin_contracts -v
uv run python -m unittest tests.test_brapi -v
```

## Provider reference

- [BrAPI API documentation index](https://brapi.dev/llms.txt)
- [BrAPI OpenAPI schema](https://brapi.dev/openapi.json)
- [BrAPI v2 dictionary](https://brapi.dev/api/v2/dictionary)
