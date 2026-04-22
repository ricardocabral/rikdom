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

## Plugin model

All rikdom plugins are Pluggy plugins declaring `module` and `class_name` in
`plugin.json`. There is no subprocess-based plugin contract: the manifest
schema rejects any field outside the set defined in
`src/rikdom/_resources/plugin.manifest.schema.json`, so a plugin must
expose a Python class that registers `@hookimpl` methods.

Use the SDK scaffold under `src/rikdom/_resources/template-plugin/`
(exposed via `rikdom plugin init`) as a ready-to-copy starting point.
