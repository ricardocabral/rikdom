# Query external data through a connector

Use this guide to discover a data connector, query a declared operation, and
inspect the returned JSON. Commands run from the repository root after
`make sync`. A portfolio workspace is not required.

The bundled [BrAPI connector](../../plugins/brapi/README.md) provides Brazilian
quotes, history, dividends, FII data, FX, and macro indicators through REST.

## Discover the connector

List the installed plugins, then inspect the one you want to use:

```bash
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom connector describe --plugin brapi --plugins-dir plugins
```

Look for `plugin_types: ["external/connector"]` and `api_version: "1.1"` in
the catalog. The description lists operation names, parameters, and the
adapter's authentication channel. Descriptions are offline by contract;
plugins are still trusted Python code when loaded.

For BrAPI, `quote` accepts the required `symbols` input, including several
tickers in the same request. Its descriptor identifies `BRAPI_TOKEN` as the
credential environment variable without revealing a token value.

## Configure authentication

For authenticated BrAPI requests, provide `BRAPI_TOKEN` through your shell
environment or credential manager. The adapter reads it and sends an
`Authorization: Bearer` header. Keep credentials out of `--params`, URLs,
manifests, saved responses, and tracked files.

PETR4 and VALE3 support public demo queries without a token. Access to other
symbols and data categories depends on the provider's plan. Each connector
owns its credential handling; the CLI does not accept a generic token flag.

## Query several symbols

```bash
uv run rikdom connector query --plugin brapi --operation quote \
  --params '{"symbols":["PETR4","VALE3"]}' --plugins-dir plugins
```

Choose other operation names from `describe`. For example, retrieve daily
history for the same symbols:

```bash
uv run rikdom connector query --plugin brapi --operation historical \
  --params '{"symbols":["PETR4","VALE3"],"range":"1mo","interval":"1d"}' \
  --plugins-dir plugins
```

Use the [BrAPI operation reference](../../plugins/brapi/README.md#operations)
for dividends, FIIs, currencies, and macro examples. Parameter names, symbol
formats, and batch limits are provider-specific; the core does not translate
them. Send only the identifiers and dates needed for the query.

## Inspect or save the result

Check these fields in the response:

- `plugin`: connector name, implementation version, and plugin API version.
- `operation`: the operation that was queried.
- `retrievedAt`: when the host received the validated result in UTC.
- `data`: provider-native JSON, including its observation timestamps and any
  warnings, errors, or missing values.

For a BrAPI quote, inspect `data.results`, then each result's `symbol` and
`data.regularMarketPrice`. Compare returned symbols with requested symbols:
the provider can omit unavailable tickers. A successful command does not
guarantee complete coverage. Treat `null` as unknown rather than zero, and
use the provider's observation time to assess freshness; `retrievedAt` is
the acquisition time.

To keep a local copy:

```bash
mkdir -p out
uv run rikdom connector query --plugin brapi --operation quote \
  --params '{"symbols":["PETR4","VALE3"]}' --plugins-dir plugins \
  > out/brapi-quote.json
```

This saves the response only. Connector queries do not update holdings,
import ledger events, or populate the canonical FX history. A saved response
is not an automatic cache or replay facility.

## Handle a failed or incomplete query

For BrAPI HTTP failures:

| Status | Action |
| --- | --- |
| `401` | Check that `BRAPI_TOKEN` is present and valid. |
| `403` | Check the provider plan's access to the requested module. |
| `404` | Check the symbols and whether the requested data exists. |
| `429` | Respect `Retry-After`; the plugin retries at most twice for waits up to 60 seconds, and reports longer delays without retrying early. |

Handled failures produce a diagnostic on stderr and exit status `1`.
Successful responses may still contain provider errors or missing symbols
under `data`; inspect those before using the result in further work.

## Use another provider or an MCP service

Select another installed connector with `--plugin`, inspect its `describe`
output, and use its declared operation and parameters with `query`. There is
no direct MCP server URL option: an MCP client belongs inside a connector
plugin, alongside its approved read operations and authentication handling.
No concrete MCP adapter is bundled yet.

To implement a provider, declare `external/connector` and API `1.1` in the
manifest, implement the offline `connector_describe` hook and read-only
`connector_query` hook, and add deterministic offline contract fixtures.
Keep provider-specific libraries and authentication handling inside the adapter. Use
the [BrAPI plugin](../../plugins/brapi/README.md) as an example and follow
the [hook contract](../reference/plugin-hooks.md#connector-hooks) and
[compatibility policy](../explanation/plugin-compatibility.md).

The core validates the descriptor and JSON boundary. Network/filesystem
isolation, credential revocation, normalized enrichment, and cached replay
remain future work; `readOnly` is a plugin declaration rather than a sandbox.
See [connector architecture](../explanation/plugin-architecture.md#external-connectors)
for the current trust model and roadmap boundaries.
