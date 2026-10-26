# Query external data through a connector

Use this guide to discover a connector, query a declared operation, and inspect
the returned JSON. Commands run from the repository root after `make sync`.
A portfolio workspace is not required. For a concrete example connector,
see [brapi](../../plugins/brapi/README.md); provider capabilities, configuration,
and runnable examples belong in each plugin's README.

## Discover a connector

List installed plugins, then select one with the `external/connector` type
and plugin API `1.1`:

```bash
uv run rikdom plugins list --plugins-dir plugins
uv run rikdom connector describe --plugin '<connector>' --plugins-dir plugins
```

Replace `<connector>` with the installed plugin's name. Its description lists
declared operation names and any plugin-defined parameter metadata.
Descriptions are offline by contract; plugins remain trusted Python code
when loaded.

## Configure the selected plugin

Follow that plugin's README for credentials, endpoints, dependencies, access
limits, and supported identifiers. The core has no generic token or endpoint
flag. Keep secrets in the plugin's documented credential channel, outside
query parameters, saved responses, and tracked files.

## Query a declared operation

Use the operation name and JSON parameter object documented by the plugin:

```bash
uv run rikdom connector query --plugin '<connector>' --operation '<operation>' \
  --params '<json-object>' --plugins-dir plugins
```

Replace all placeholders before running. Parameter names, batching support,
identifier formats, and limits belong to the plugin. Send only the identifiers
and dates needed for the query. The core checks that the operation is declared
and that parameters are a JSON object; the plugin validates their meaning.

## Inspect or save the result

Check these fields in the response:

- `plugin`: connector name, implementation version, and plugin API version.
- `operation`: the operation that was queried.
- `retrievedAt`: when the host received the validated result in UTC.
- `data`: provider-native JSON. Consult the plugin's documentation for its
  structure, observation timestamps, warnings, and errors.

Check whether all requested identifiers were returned before treating a batch
as complete. Treat `null` as unknown rather than zero, and use observation
timestamps to assess freshness; `retrievedAt` is the acquisition time.

To save a response locally, redirect the command's stdout:

```bash
mkdir -p out
uv run rikdom connector query --plugin '<connector>' --operation '<operation>' \
  --params '<json-object>' --plugins-dir plugins > out/connector-response.json
```

A saved response is not an automatic cache or replay facility. Connector
queries do not update holdings, import ledger events, or populate canonical
FX history.

## Handle a failed or incomplete query

Handled failures produce a diagnostic on stderr and exit status `1`. Follow
the selected plugin's troubleshooting instructions for authentication,
permissions, missing data, and rate limits. Respect any reported retry delay.
Successful responses may still contain provider errors or incomplete data;
inspect the payload before using it in further work.

## Implement another provider or an MCP service

Declare `external/connector` and API `1.1` in the manifest, implement the
offline `connector_describe` hook and read-only `connector_query` hook, and
add deterministic offline contract fixtures. Keep provider-specific libraries,
authentication, configuration, capabilities, and examples inside the plugin.
Follow the [hook contract](../reference/plugin-hooks.md#connector-hooks) and
[compatibility policy](../explanation/plugin-compatibility.md).

REST and MCP clients use the same boundary. An MCP client belongs inside a
connector plugin with its approved read operations; there is no direct MCP
server URL option or bundled MCP adapter yet.

The core validates the descriptor and JSON boundary. Network/filesystem
isolation, credential revocation, normalized enrichment, and cached replay
remain future work; `readOnly` is a declaration rather than a sandbox. See
[connector architecture](../explanation/plugin-architecture.md#external-connectors)
for the trust model and roadmap boundaries.
