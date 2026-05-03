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
| `observability` | fan-out | Stable |
| `audit_trail` | fan-out | Stable |

See [plugin compatibility](../explanation/plugin-compatibility.md) for the
deprecation window applied to Stable hooks.

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

## Contract test fixtures

Every Pluggy plugin that declares a v1 data hook (`source_input`,
`asset_type_catalog`, `output`, `state_storage_sync`, `state_storage_query`,
`state_storage_health`) must ship at least one contract-test fixture. CI
fails when a plugin declares a data hook with zero fixtures.

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
