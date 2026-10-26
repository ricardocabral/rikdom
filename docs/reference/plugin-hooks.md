# Plugin Hooks Reference

Hook specs are defined in `src/rikdom/plugin_engine/hookspecs.py`. Stability
tiers are in `HOOK_STABILITY` in the same module.

## Hookspec surface

```python
class RikdomHookSpecs:
    def source_input(self, ctx, input_path): ...
    def asset_type_catalog(self, ctx): ...
    def output(self, ctx, request): ...
    def state_storage_sync(self, ctx, portfolio_path, snapshots_path, options): ...
    def state_storage_query(self, ctx, query_name, params): ...
    def state_storage_health(self, ctx, options): ...
    def connector_describe(self, ctx) -> dict: ...
    def connector_query(self, ctx, operation: str, params: dict) -> dict: ...
    def observability(self, ctx, event, payload): ...
    def audit_trail(self, ctx, event, payload): ...
```

## Dispatch and stability

| Hook | Dispatch | Stability (v1) |
| --- | --- | --- |
| `source_input` | firstresult | Stable |
| `asset_type_catalog` | fan-out (merged by `id`) | Stable |
| `output` | firstresult | Stable |
| `state_storage_sync` | firstresult | Stable |
| `state_storage_query` | firstresult | Stable |
| `state_storage_health` | firstresult | Stable |
| `connector_describe` | firstresult | Experimental |
| `connector_query` | firstresult | Experimental |
| `observability` | fan-out | Stable |
| `audit_trail` | fan-out | Stable |

See [plugin compatibility](../explanation/plugin-compatibility.md) for the
deprecation window applied to Stable hooks.

Connector hooks are additive in plugin API `1.1`; existing `1.0` plugins and
Stable hook contracts remain unchanged. Connectors use the `external/connector`
plugin type.

## Shared runtime objects

- `ctx`: `PluginContext(run_id, plugin_name, metadata={})`
- `request` (output hook): `OutputRequest(portfolio_path, snapshots_path, output_dir, options={})`

## Result shapes

| Hook | Return shape |
| --- | --- |
| `source_input` | `dict` — normalized statement payload (see below) |
| `asset_type_catalog` | `list[dict]` — entries merged by unique `id` |
| `output` | `dict` with `plugin`, `artifacts`, optional `warnings` |
| `state_storage_sync` | `dict` with `rows_written`, backend path, hashes, `warnings` |
| `state_storage_query` | `dict` query result payload |
| `state_storage_health` | `dict` health status payload |
| `connector_describe` | Versioned read-only capability `dict` (see below) |
| `connector_query` | `dict` containing provider-native JSON |
| `observability` / `audit_trail` | side-effect; return ignored |

### `source_input` payload shape

Consumed by `run_import_pipeline` and `cmd_import_statement` (see
`src/rikdom/cli.py` and `plugins/csv-generic/` for the richest reference):

- `provider` (string): default `source_system` for the import log.
- `generated_at` (ISO-8601 string): statement generation timestamp.
- `holdings` (list of dicts): each requires `id`, `asset_type_id`, `label`,
  `market_value.amount`, `market_value.currency`; optional `quantity`,
  `identifiers`, `metadata`.
- `activities` (optional list): ledger events if the source exposes them.

### Connector hooks

`connector_describe(ctx)` must return an offline, credential-free description:

```json
{
  "contractVersion": "1.0",
  "readOnly": true,
  "operations": {
    "lookup": {"parameters": ["ids"], "requiredParameters": ["ids"]}
  }
}
```

The host requires exactly the supported `contractVersion`, `readOnly: true`,
and a non-empty `operations` object mapping non-blank names to objects. Extra
description fields and operation details are provider-defined JSON; the host
does not interpret fields such as `parameters` or `requiredParameters`.
Plugins validate their own operation parameters. `readOnly` declares the
plugin's contract; it is not a sandbox or enforceable access permission.

`connector_query(ctx, operation, params)` executes one declared operation. The
host checks the descriptor before dispatch, rejects undeclared operations, and
gives the plugin a detached copy of the caller's JSON parameters. Parameters,
descriptions, and results must be strict JSON objects: nested arrays, objects,
strings, booleans, finite numbers, and `null` are accepted; non-string keys,
NaN, Infinity, cycles, and arbitrary Python values are rejected.

The core does not interpret provider symbols, credentials, or transport. REST
clients and MCP clients belong inside individual plugins. A future MCP plugin
must expose its approved read operations through this contract; this interface
does not provide a general-purpose remote tool executor. No concrete MCP
transport is included yet.

```bash
uv run rikdom connector describe --plugin '<connector>' --plugins-dir plugins
uv run rikdom connector query --plugin '<connector>' --operation lookup \
  --params '{"ids":["example-1","example-2"]}' --plugins-dir plugins
```

Replace `<connector>` with an installed plugin. `lookup` and `ids` illustrate
the contract; use the operation and parameters declared by that plugin.

The hook returns raw provider JSON. `run_connector_query_pipeline` and the CLI
wrap it in a host-owned acquisition envelope:

```json
{
  "contractVersion": "1.0",
  "plugin": {"name": "example", "version": "0.1.0", "apiVersion": "1.1"},
  "operation": "lookup",
  "retrievedAt": "2026-10-26T12:00:00+00:00",
  "data": {"results": [{"id": "example-1", "value": null}]}
}
```

`retrievedAt` records when the host received a validated result, not the market
observation's effective time. Provider fields, including `null`, error objects,
and warnings, are preserved under `data`; they cannot overwrite host metadata.
An envelope records retrieval, not financial validity or complete coverage.
The host does not echo request parameters or credentials into the envelope.
Plugins must keep credentials out of their descriptions, results, and errors.

These results do not conform to the statement import schema. The connector
pipeline receives no canonical file paths and does not merge holdings, import
ledger events, or write portfolio files. Local plugins remain trusted Python
with process-level access, so these are interface guarantees, not isolation.
Provider operations and authentication rules belong in each plugin's README.

## Contract test fixtures

Every Pluggy plugin that declares a v1 data hook (`source_input`,
`asset_type_catalog`, `output`, `state_storage_sync`, `state_storage_query`,
`state_storage_health`, `connector_describe`, `connector_query`) must ship at
least one contract-test fixture. CI fails when a plugin declares a data hook
with zero fixtures.

### Fixture layout

```
plugins/<plugin-name>/fixtures/<case>/
  case.json           # required — describes hook + inputs
  input.*             # required for source_input hooks
  portfolio.json      # required for output / state_storage_sync hooks
  snapshots.jsonl     # required for output / state_storage_sync hooks
  expected.json       # canonical expected payload
  expected.jsonl      # alternative line-delimited form
  expected_error.json # alternative — for failure-mode fixtures
```

### `case.json` keys

| Key | Required | Description |
| --- | --- | --- |
| `hook` | yes | One of the v1 hook names above. |
| `input` | source_input | Filename inside the fixture dir (defaults to first `input.*` match). |
| `portfolio` / `snapshots` | output, sync | Filenames inside the fixture dir. Default `portfolio.json` / `snapshots.jsonl`. |
| `options` | optional | `dict` passed through to hooks that accept options. |
| `query_name` / `params` | query | Inputs for `state_storage_query`. |
| `operation` / `params` | connector_query | Provider operation string and JSON object passed to `connector_query`. |
| `env` | optional | Env vars set for the duration of the invocation (e.g. `RIKDOM_DISABLE_QUARTO=1`). |
| `requires` | optional | Importable modules that must be available — case skipped if any is missing (e.g. `["duckdb"]`). |
| `ignore_fields` | optional | Keys to strip *anywhere* in the payload tree before equality/determinism compare. `generated_at` is always stripped. |
| `validate_schema` | optional | Canonical JSON Schema alias: `plugin-statement`, `portfolio`, or `snapshot`. |

### Determinism contract

For each case the runner invokes the hook twice in fresh tmpdirs and asserts
byte-identical canonical JSON after `ignore_fields` are stripped. The contract
uses a fixed `PluginContext.run_id` (`contract-<plugin>-<case>`) so any hook
that seeds IDs from the context produces identical output. Hooks that pull
`datetime.now()` should list the offending field name in `ignore_fields`;
`generated_at` is stripped by default.

Connector fixtures must run offline with deterministic results. The runner
uses the same descriptor, operation, and JSON validation as the runtime; query
fixtures compare the validated raw payload, before the CLI adds its retrieval
timestamp. A `connector_describe` case needs only its hook name and expected
result. A query case supplies `operation` and `params` and may exercise invalid
input with an `expected_error.json` fixture. Cover successful offline dispatch
as well as rejected operations. Mock external I/O in transport tests to
exercise successful responses, authentication, and rate limits without
provider access. This does not implement cached response replay or an enforced
network sandbox.

### Failure-mode fixtures

Drop an `expected_error.json` (instead of `expected.json`) with
`{"type": "<ExceptionClassName>", "message_contains": "<substring>"}` to
assert that a given input causes the hook to raise a specific error.

### Running the contract suite

```bash
uv run python -m unittest tests.test_plugin_contracts -v
```

CI runs the same command in a dedicated job.

## See also

- [Plugin manifest reference](plugin-manifest.md)
- [Plugin architecture](../explanation/plugin-architecture.md)
