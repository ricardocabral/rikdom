# Plugin Manifest Reference

Every plugin declares itself through `plugins/<plugin-name>/plugin.json`.
The manifest schema is bundled at
`src/rikdom/_resources/plugin.manifest.schema.json` and shipped as a package
resource so it resolves in installed distributions.

## Minimal example

```json
{
  "name": "quarto-portfolio-report",
  "version": "0.1.0",
  "api_version": "1.0",
  "plugin_types": ["output"],
  "module": "plugin",
  "class_name": "Plugin",
  "description": "Render portfolio report with Quarto"
}
```

## Fields

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `name` | yes | string | Plugin slug. Must match `^[a-z][a-z0-9-]{1,63}$`. Matches the directory name. |
| `version` | yes | string | Plugin's own semver. |
| `api_version` | optional | string | Rikdom plugin API version. Defaults to `"1.0"`. Only `"1.0"` is currently accepted. See [plugin compatibility](../explanation/plugin-compatibility.md). |
| `plugin_types` | yes | string[] | One or more entries from the [taxonomy](../explanation/plugin-architecture.md#plugin-taxonomy). |
| `module` | yes | string | Python module name (without `.py`) inside the plugin directory. |
| `class_name` | yes | string | Class inside `module` that registers `@hookimpl` methods. |
| `description` | optional | string | Human-readable description. |

The manifest schema rejects any field outside this set.

## Discovery

```bash
uv run rikdom plugins list --plugins-dir plugins
```

Each entry in the output includes `api_version`, `plugin_types`, `module`,
and `class_name` — the fields needed to load the plugin through Pluggy.

## See also

- [Plugin hooks reference](plugin-hooks.md)
- [Plugin compatibility](../explanation/plugin-compatibility.md) — version policy.
- [Author your first plugin](../tutorials/first-plugin.md)
