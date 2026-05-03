# Tutorial: Author your first plugin

This tutorial walks you through scaffolding, implementing, and running a
working `source/input` plugin using the bundled SDK template. By the end you
will have a plugin that imports a CSV statement into your local portfolio.

If you want background instead of a guided lesson, see
[plugin architecture](../explanation/plugin-architecture.md). For full field
references see [plugin manifest](../reference/plugin-manifest.md) and
[plugin hooks](../reference/plugin-hooks.md).

## What you will build

A plugin called `my-plugin` that:

1. Lives at `plugins/my-plugin/`.
2. Implements the `source_input` hook.
3. Parses a tiny sample CSV.
4. Imports holdings into your `data/portfolio.json` workspace.

Estimated time: 10 minutes.

## Prerequisites

- You completed [Your first portfolio](first-portfolio.md), or an equivalent
  workspace exists at `data/`.
- `uv` is installed and `make sync` has run.

## 1. Bootstrap from the scaffold

The slug must match `^[a-z][a-z0-9-]{1,63}$`:

```bash
uv run rikdom plugin init my-plugin --dest plugins --description "Parse my broker statement"
```

The command refuses to overwrite an existing directory. Result:

```text
plugins/my-plugin/
  plugin.json           # Manifest, validated against the bundled schema
  plugin.py             # Plugin class with @hookimpl source_input
  README.md             # Authoring notes
  fixtures/sample.csv   # Three-row CSV used by the smoke test
  tests/test_plugin.py  # Unittest exercising parse_statement() and the hook
```

## 2. Inspect the implementation

Open `plugins/my-plugin/plugin.py`. The scaffold already implements
`source_input`. The minimal shape looks like:

```python
from rikdom.plugin_engine.hookspecs import hookimpl


class Plugin:
    @hookimpl
    def source_input(self, ctx, input_path):
        return {
            "provider": "my-plugin",
            "generated_at": "2026-04-21T00:00:00Z",
            "holdings": [
                {
                    "id": "AAPL",
                    "asset_type_id": "stock",
                    "label": "AAPL",
                    "quantity": 10,
                    "market_value": {"amount": 1800.0, "currency": "USD"},
                    "identifiers": {"ticker": "AAPL"},
                }
            ],
        }
```

The full payload contract is documented in
[plugin hooks](../reference/plugin-hooks.md#source_input-payload-shape).

## 3. Run the plugin's own tests

```bash
cd plugins/my-plugin
uv run python -m unittest tests.test_plugin
```

The scaffold's test imports `plugin` directly, so no packaging or
`PYTHONPATH` setup is needed.

## 4. Verify discovery

From the repo root:

```bash
uv run rikdom plugins list --plugins-dir plugins
```

Look for `my-plugin` in the output. Each entry includes `api_version`,
`plugin_types`, `module`, and `class_name`.

## 5. Run the import pipeline

Dry-run first to see the merge plan without touching `data/portfolio.json`:

```bash
uv run rikdom import-statement \
  --plugin my-plugin \
  --input plugins/my-plugin/fixtures/sample.csv \
  --data-dir data --out-root out \
  --dry-run
```

Then `--write` to merge into the workspace portfolio:

```bash
uv run rikdom import-statement \
  --plugin my-plugin \
  --input plugins/my-plugin/fixtures/sample.csv \
  --data-dir data --out-root out \
  --write
```

## 6. Confirm the import

```bash
uv run rikdom validate --data-dir data --out-root out
uv run rikdom aggregate --data-dir data --out-root out
```

Your imported holdings now flow through validation and aggregation just
like any other portfolio data.

## Where to go next

- Add a contract-test fixture so CI can verify your plugin's determinism —
  see [plugin hooks reference](../reference/plugin-hooks.md#contract-test-fixtures).
- Read [plugin architecture](../explanation/plugin-architecture.md) to
  understand the lifecycle and dispatch model.
- Review [plugin compatibility](../explanation/plugin-compatibility.md)
  before publishing or sharing your plugin.
