# Rikdom Plugin Scaffold

This template is instantiated by `rikdom plugin init <name>`. It provides
a minimum-viable Pluggy plugin that implements the `source/input`
plugin type, parses a trivial CSV fixture, and returns a normalized
statement payload that the rikdom import pipeline can consume.

## Layout

```
<plugin-name>/
  plugin.json           # Manifest (api_version 1.0, validated against
                        # the bundled rikdom._resources/plugin.manifest.schema.json)
  plugin.py             # Plugin class with @hookimpl source_input
  fixtures/sample.csv   # Three-row CSV used by the smoke test
  tests/test_plugin.py  # Unittest that exercises parse_statement()
```

## Run the test

From inside the generated plugin directory:

```bash
uv run python -m unittest tests.test_plugin
```

The test imports the local `plugin` module directly, so no packaging
step is required.

## Register the plugin

Rikdom discovers plugins by scanning a directory for `plugin.json`
manifests. If you accept the default `--dest plugins`, the plugin is
discovered automatically by:

```bash
uv run rikdom plugins list --plugins-dir plugins
```

If you generated into a custom directory, point `--plugins-dir` at it.

## Next steps

- Flesh out `parse_statement` to accept the columns your upstream
  statement actually produces; the scaffold expects
  `symbol,quantity,price,currency,as_of_date`.
- Add activities to the returned payload if your source exposes them
  (see `plugins/csv-generic/` for a richer reference).
- See `docs/plugin-system.md` for the full plugin authoring guide,
  including hook semantics, manifest fields, and API v1 stability
  guarantees.
