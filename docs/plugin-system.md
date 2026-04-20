# Plugin System

This guide is the fastest path to implement new `rikdom` plugins safely.

## TL;DR

- Discover plugins from `plugins/<name>/plugin.json`.
- Use `uv run rikdom plugins list --plugins-dir plugins` to verify manifest loading.
- `import-statement` currently executes **legacy command-based** plugins.
- `render-report` and `storage-sync` execute **Pluggy module/class** plugins.
- Prefer Pluggy manifests for new work; keep legacy `command` when you need `import-statement` compatibility.

## Taxonomy And Current Execution Support

`rikdom` defines these plugin types in `PhaseName`:

- Lifecycle: `source/input`, `transform`, `enrichment`, `strategy/decision`, `execution`, `output`
- Cross-cutting and platform: `risk/compliance`, `state/storage`, `orchestration`, `observability`, `auth/security`, `notification`, `simulation/backtest`, `asset-type/catalog`

What is wired today:

- `import-statement` -> legacy command plugin (`plugin.json.command`) for `source/input`
- `render-report` -> Pluggy hook `output`
- `storage-sync` -> Pluggy hook `state_storage_sync`
- Internal Pluggy hooks also exist for `asset_type_catalog`, `state_storage_health`, `state_storage_query`, `observability`, `audit_trail`

## Manifest Schema (Compatibility)

### Legacy manifest (import command runner)

Use when plugin is invoked via `import-statement` today.

```json
{
  "name": "csv-generic",
  "version": "0.1.0",
  "description": "Import holdings from a generic CSV statement",
  "command": ["python3", "importer.py"]
}
```

Notes:

- `command` runs in the plugin directory.
- CLI appends the input file path as the last argument.
- Plugin must print JSON to stdout with a `holdings` array.

### Pluggy manifest (recommended new style)

Use for new output/storage/catalog plugins and any future-first plugin.

```json
{
  "name": "quarto-portfolio-report",
  "version": "0.1.0",
  "api_version": "1.0",
  "plugin_types": ["output"],
  "module": "plugin",
  "class_name": "Plugin",
  "description": "Render portfolio graphics through Quarto"
}
```

Notes:

- `module` maps to `<plugin-dir>/<module>.py`.
- `class_name` is instantiated with no args.
- `plugin_types` must include the phase used by the CLI/pipeline.
- Compatibility pattern: you can include both `command` and Pluggy fields in one manifest.

### Field reference

- Required in all manifests: `name`, `version`
- Optional with defaults: `api_version` (`"1.0"`), `description` (`""`), `plugin_types` (`[]`)
- Legacy execution field: `command: string[]`
- Pluggy execution fields: `module: string`, `class_name: string`

## Hook Signatures And Return Contracts

Current hook specs:

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

Context and request types:

- `ctx`: `PluginContext(run_id: str, plugin_name: str, metadata: dict = {})`
- `request` for `output`: `OutputRequest(portfolio_path, snapshots_path, output_dir, options={})`

Expected payloads by hook:

- `source_input` -> `dict`.
- `asset_type_catalog` -> `list[dict]` per plugin (engine merges unique `id`).
- `output` -> `dict` like:
  - `plugin: str`
  - `artifacts: list[{"type": str, "path": str}]`
  - `warnings: list[str]` (optional but recommended)
- `state_storage_sync` -> `dict` like:
  - `rows_written: dict[str, int]`
  - `db_path: str`
  - `source_hash_portfolio: str`
  - `source_hash_snapshots: str`
  - `warnings: list[str]`
- `state_storage_health` -> `dict` health metadata.
- `state_storage_query` -> `dict` query result payload.
- `observability` / `audit_trail` -> side-effect hooks; return value is not used.

## End-to-End Examples

### 1) Source/Input plugin (import)

Manifest (legacy mode):

```json
{
  "name": "csv-generic",
  "version": "0.1.0",
  "description": "Import holdings from a generic CSV statement",
  "command": ["python3", "importer.py"]
}
```

Runner command:

```bash
uv run rikdom import-statement \
  --portfolio data/portfolio.json \
  --plugin csv-generic \
  --input data/sample_statement.csv
```

Expected CLI response shape:

```json
{
  "plugin": "csv-generic",
  "inserted": 2,
  "updated": 0,
  "write": false
}
```

### 2) Output plugin (Quarto-like)

Manifest (Pluggy mode):

```json
{
  "name": "quarto-portfolio-report",
  "version": "0.1.0",
  "api_version": "1.0",
  "plugin_types": ["output"],
  "module": "plugin",
  "class_name": "Plugin"
}
```

Hook implementation shape:

```python
from rikdom.plugin_engine.hookspecs import hookimpl

class Plugin:
    @hookimpl
    def output(self, ctx, request):
        # read request.portfolio_path / request.snapshots_path
        # write report artifacts into request.output_dir
        return {
            "plugin": "quarto-portfolio-report",
            "artifacts": [
                {"type": "html", "path": "out/reports/portfolio-report.html"},
                {"type": "json", "path": "out/reports/quarto-input.json"}
            ],
            "warnings": []
        }
```

Runner command:

```bash
uv run rikdom render-report \
  --plugin quarto-portfolio-report \
  --plugins-dir plugins \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --out-dir out/reports
```

### 3) State/Storage plugin (DuckDB-like)

Manifest (Pluggy mode):

```json
{
  "name": "duckdb-storage",
  "version": "0.1.0",
  "api_version": "1.0",
  "plugin_types": ["state/storage"],
  "module": "plugin",
  "class_name": "Plugin"
}
```

Hook implementation shape:

```python
from rikdom.plugin_engine.hookspecs import hookimpl

class Plugin:
    @hookimpl
    def state_storage_sync(self, ctx, portfolio_path, snapshots_path, options):
        return {
            "rows_written": {"portfolio_header": 1, "holdings": 6, "snapshots": 4},
            "db_path": options.get("db_path", "out/rikdom.duckdb"),
            "source_hash_portfolio": "...",
            "source_hash_snapshots": "...",
            "warnings": []
        }

    @hookimpl
    def state_storage_health(self, ctx, options):
        return {"status": "ok", "db_path": options.get("db_path", "out/rikdom.duckdb")}
```

Runner command:

```bash
uv run rikdom storage-sync \
  --plugin duckdb-storage \
  --plugins-dir plugins \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --db-path out/rikdom.duckdb
```

## Security And Permissions Guidance

Treat plugin execution as code execution.

- Legacy `command` plugins spawn subprocesses and can run any binary/script available in the environment.
- Pluggy plugins run in-process and have full Python access to local files and network (if environment allows).
- Restrict plugin writes to intended output paths (`out/...` by default).
- Do not execute shell strings (`shell=True` patterns); keep commands as explicit argv arrays.
- Validate and normalize file paths from plugin options (`db_path`, output directories, input files).
- Never hardcode credentials, tokens, API keys, or secret URLs in plugin code or fixtures.
- Emit warnings when running in skeleton/no-op modes so operators do not assume data was persisted.

## Plugin Author Testing Checklist

1. Manifest loads and is discoverable.
2. Plugin command/hook executes on sample data.
3. Return payload has required keys for its hook.
4. Artifacts are written to expected paths.
5. Determinism: same input produces equivalent output.
6. Failure path is clear (invalid input returns useful error).

Recommended commands:

```bash
uv run rikdom plugins list --plugins-dir plugins

uv run rikdom import-statement \
  --plugin csv-generic \
  --input data/sample_statement.csv \
  --portfolio data/portfolio.json

uv run rikdom render-report \
  --plugin quarto-portfolio-report \
  --plugins-dir plugins \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --out-dir out/reports

uv run rikdom storage-sync \
  --plugin duckdb-storage \
  --plugins-dir plugins \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --db-path out/rikdom.duckdb

uv run pytest -q \
  tests/test_plugins.py \
  tests/test_b3_consolidado_mensal_plugin.py \
  tests/test_output_plugin_pipeline.py \
  tests/test_quarto_report_mapping.py \
  tests/test_duckdb_storage_plugin.py
```
