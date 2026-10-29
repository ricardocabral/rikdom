# Plugin Compatibility and Stability

This document explains the versioning and stability policy for the rikdom
plugin API. It complements the [plugin architecture](plugin-architecture.md)
and the [plugin manifest reference](../reference/plugin-manifest.md).

## `api_version` semver policy

Every plugin manifest declares an `api_version` field that pins the plugin
against a specific rikdom plugin API contract. The field is required and
validated by the bundled manifest schema at
`src/rikdom/_resources/plugin.manifest.schema.json` (shipped as a package
resource so it resolves in installed distributions too).

- The runtime accepts `"1.0"`, `"1.1"` and `"1.2"`. API `"1.1"` adds the Experimental
  `external/connector` query and discovery hooks. Existing plugins declaring
  `"1.0"` keep working unchanged; the schema requires connector plugins to
  target `"1.1"` or `"1.2"`. API `"1.2"` adds the Experimental
  normalized `enrichment` hook, which requires `"1.2"`.
- Future **minor** bumps (`"1.3"`, ...) are additive for Stable surfaces. They
  may introduce new hooks or new optional manifest fields, but must not
  change or remove anything declared in `"1.0"`. Plugins declaring `"1.0"`
  keep working unchanged. Experimental hooks follow the exception below.
- Future **major** bumps (`"2.0"`) may remove hooks, change hook signatures,
  or tighten schema constraints. Any such change ships only after a
  deprecation window (see below).
- The engine rejects unknown `api_version` values at manifest load time via
  the schema enum, so plugins that target a version the runtime does not
  recognize fail fast with a clear error.

## Stability tiers per hook

All eight API 1.0 hooks remain Stable. API 1.1 adds Experimental
`connector_describe` and `connector_query` hooks. API 1.2 adds Experimental
`enrichment` for normalized local series and host-derived lookups. The mapping mirrors the
`HOOK_STABILITY` constant in `src/rikdom/plugin_engine/hookspecs.py`, which
documentation and tooling can import directly.

See the [plugin hooks reference](../reference/plugin-hooks.md) for the
dispatch + stability table.

Future minor bumps may introduce **experimental** hooks. Experimental hooks
are explicitly marked in `HOOK_STABILITY` and may change signature or be
removed between minor releases without a deprecation window. Stable hooks
never degrade in place.

Connector descriptions and CLI query envelopes declare `contractVersion:
"1.0"`. This is the experimental connector payload version, separate from
the manifest's `api_version: "1.1"` and the plugin's implementation `version`.
The host rejects unsupported description versions. A future incompatible
connector payload must use a new contract version and document migration;
it must not silently reinterpret saved `1.0` envelopes. The current envelope
preserves raw acquisition provenance. API 1.2 enrichment uses a separate
`contract_version: "1.0"` envelope and validates MarketSeries 1.0 documents;
see [normalized enrichment](../reference/enrichment.md).

## Deprecation window

Any removal or breaking change to a Stable surface follows this policy:

- At least **two minor releases** of deprecation warnings must ship before a
  major bump removes the surface.
- Deprecations are surfaced through the `observability` hook (emitting a
  `plugin.deprecation` event at load time) and, where practical, called out
  in `rikdom plugins list` output so operators notice before upgrading.
- The deprecation note in release notes names the replacement and the
  earliest major version that may remove the old surface.

## Pluggy-only model

All rikdom plugins are Pluggy plugins declaring `module` and `class_name` in
`plugin.json`. There is no subprocess-based plugin contract: the manifest
schema rejects any field outside the set defined in
`src/rikdom/_resources/plugin.manifest.schema.json`, so a plugin must
expose a Python class that registers `@hookimpl` methods.

Use the SDK scaffold under `src/rikdom/_resources/template-plugin/`
(exposed via `rikdom plugin init`), or `template-enrichment` selected with
`rikdom plugin init NAME --type enrichment`, as a ready-to-copy starting point — see
[author your first plugin](../tutorials/first-plugin.md).

## See also

- [Plugin architecture](plugin-architecture.md)
- [Plugin manifest reference](../reference/plugin-manifest.md)
- [Plugin hooks reference](../reference/plugin-hooks.md)
