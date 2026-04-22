# Plugin Compatibility and Stability

This document defines the versioning and stability policy for the rikdom
plugin API. It complements the authoring guide in
[plugin-system.md](plugin-system.md).

## `api_version` semver policy

Every plugin manifest declares an `api_version` field that pins the plugin
against a specific rikdom plugin API contract. The field is required and
validated by the bundled manifest schema at
`src/rikdom/_resources/plugin.manifest.schema.json` (shipped as a package
resource so it resolves in installed distributions too).

- v1 is the string `"1.0"`. It is the only currently accepted value; the
  schema enum rejects anything else.
- Future **minor** bumps (`"1.1"`, `"1.2"`, ...) are strictly additive. They
  may introduce new hooks or new optional manifest fields, but must not
  change or remove anything declared in `"1.0"`. Plugins declaring `"1.0"`
  keep working unchanged.
- Future **major** bumps (`"2.0"`) may remove hooks, change hook signatures,
  or tighten schema constraints. Any such change ships only after a
  deprecation window (see below).
- The engine rejects unknown `api_version` values at manifest load time via
  the schema enum, so plugins that target a version the runtime does not
  recognize fail fast with a clear error.

## Stability tiers per hook

All eight v1 hooks are Stable. The mapping below mirrors the
`HOOK_STABILITY` constant in `src/rikdom/plugin_engine/hookspecs.py`, which
documentation and tooling can import directly.

| Hook | Dispatch | Stability (v1) |
| --- | --- | --- |
| `source_input` | firstresult | Stable |
| `asset_type_catalog` | fan-out | Stable |
| `output` | firstresult | Stable |
| `state_storage_sync` | firstresult | Stable |
| `state_storage_query` | firstresult | Stable |
| `state_storage_health` | firstresult | Stable |
| `observability` | fan-out | Stable |
| `audit_trail` | fan-out | Stable |

Future minor bumps may introduce **experimental** hooks. Experimental hooks
are explicitly marked in `HOOK_STABILITY` and may change signature or be
removed between minor releases without a deprecation window. Stable hooks
never degrade in place.

## Deprecation window

Any removal or breaking change to a Stable surface follows this policy:

- At least **two minor releases** of deprecation warnings must ship before a
  major bump removes the surface.
- Deprecations are surfaced through the `observability` hook (emitting a
  `plugin.deprecation` event at load time) and, where practical, called out
  in `rikdom plugins list` output so operators notice before upgrading.
- The deprecation note in release notes names the replacement and the
  earliest major version that may remove the old surface.

## Legacy `command` -> Pluggy migration

The older subprocess-style plugin contract remains supported in v1:

- When a manifest declares `command` (a non-empty array of strings), rikdom
  invokes that command as a subprocess through the legacy code path in
  `src/rikdom/plugins.py`. Only the `import-statement` CLI dispatches
  through this path today; all other plugin types are Pluggy-only.
- `rikdom plugins list` marks these entries with `"legacy": true`, so you
  can inventory remaining subprocess plugins at a glance.

### Migration recipe

1. Port the subprocess logic into a Python class with a
   `@hookimpl source_input` method that returns the same normalized payload
   the subprocess used to emit on stdout.
2. Remove `command` from `plugin.json`.
3. Add `module` and `class_name` (typically `"plugin"` and `"Plugin"`) to
   the manifest, keeping `api_version: "1.0"`.
4. Scaffold the test layout with `uv run rikdom plugin init ...` in a scratch
   directory and copy `tests/test_plugin.py` + `fixtures/` into the plugin
   to lock in the shape.

The SDK scaffold under `src/rikdom/_resources/template-plugin/` (exposed
via `rikdom plugin init`) is a ready-to-copy starting point.

### Timeline

- **v1 (now)**: legacy `command` manifests keep working; new plugins should
  use the Pluggy contract.
- **Later v1.x**: once all bundled plugins under `plugins/` have migrated,
  the legacy path enters the deprecation window described above.
- **v2**: the legacy `command` path is removed. All plugins must be Pluggy
  classes by then.
