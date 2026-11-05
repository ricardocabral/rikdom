# Rikdom Export Bundle Format

A `rikdom-export` bundle is a ZIP file for archival and interchange. It
stores canonical rikdom data files plus a checksum manifest that importers
verify before writing anything.

## Archival data bundles (v1)

`rikdom export` continues to write format `1.0.0`. These bundles preserve data;
they do not claim to capture a calculation.

### Layout

```text
rikdom-export.zip
├── rikdom-export.json
└── data/
    ├── portfolio.json
    ├── snapshots.jsonl      # optional
    ├── fx_rates.jsonl       # optional
    └── policy.json          # optional
```

### Manifest

`rikdom-export.json` is JSON with:

- `format`: always `rikdom-export`
- `format_version`: bundle format semver
- `created_at`: UTC timestamp
- `entries[]`: one entry per payload, including:
  - `path`
  - `kind` (`portfolio`, `snapshots`, `fx_history`, `policy`)
  - `media_type`
  - `schema_uri` and, when present in the payload, `schema_version`
  - `bytes`
  - `sha256`
  - `records` for JSONL files

Example:

```json
{
  "format": "rikdom-export",
  "format_version": "1.0.0",
  "created_at": "2026-04-29T13:00:00Z",
  "entries": [
    {
      "path": "data/portfolio.json",
      "kind": "portfolio",
      "media_type": "application/json",
      "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
      "schema_version": "1.4.0",
      "bytes": 12345,
      "sha256": "..."
    }
  ]
}
```

## CLI

Create a bundle:

```sh
rikdom export --output out/rikdom-export.zip
```

Verify a bundle without applying it:

```sh
rikdom verify-export --bundle out/rikdom-export.zip
```

Import after checksum verification:

```sh
rikdom import-export --bundle out/rikdom-export.zip
```

Import supports workspace path options (`--data-dir`, `--portfolio-name`,
`--registry`) and writes `.bak-<timestamp>` backups for overwritten files
unless `--no-backup` is supplied.

## Reproducible aggregate bundles (v2)

Capture the actual inputs and result of an aggregation:

```sh
rikdom aggregate --data-dir data --bundle out/aggregate.zip
rikdom verify-export --bundle out/aggregate.zip
rikdom replay-export --bundle out/aggregate.zip --restore-dir restored-analysis
```

`--restore-dir` must not exist. Install the required runtime/dependencies before
replay; the replay command does not download data, load plugins, run bundled code,
or install dependencies. It works without the original workspace or statements.

```text
aggregate.zip
├── rikdom-export.json       # format_version: 2.0.0
├── data/portfolio.json      # normalized inputs actually used, including corrections
├── analysis/run.json        # versioned calculation manifest
├── analysis/result.json     # expected aggregate CLI output
└── environment/uv.lock      # included when available in the source installation
```

The outer manifest retains v1's size and SHA-256 verification semantics and adds
`analysis_run`, `analysis_result`, and optional `dependency_lock` payload kinds.
Every v2 bundle requires portfolio, run, and result payloads. The run manifest has:

- `format: rikdom-analysis-run`, `format_version: 1.0.0`, and `created_at`.
- `method: {name: aggregate, version: 1.0.0}`.
- `inputs.portfolio` and `result` path/SHA-256 references matching the payloads.
- `parameters.strict`, the exact selected `fx_lock` (rates, dates, sources and
  valuation timestamp), and the FX diagnostics emitted during selection.
- `environment`: Python version/implementation, installed Rikdom package version,
  a hash of installed core Python source, and dependency versions. This first
  slice requires an exact environment match. `plugins: []` explicitly records
  that no plugins participated in this calculation.
- `dependency_lock`: included path/SHA-256 or an explicit `unavailable` status and
  reason when the source installation has no `uv.lock`. An unavailable lock is
  disclosed and never fetched; the recorded environment is still required.
- `equality`: fixed absolute tolerance `1e-8` and relative tolerance `1e-12`.

Method `aggregate/1.0.0` uses the installed aggregation engine with binary64
arithmetic, unrounded output, quantity tolerance `1e-6`, and cash drift tolerance
`0.01` in base currency. It applies recorded FX rates with the engine's usual
holding FX precedence. Replay reuses the selected rates, without selecting newer
observations. Currency, dimension keys, warnings and errors must match; finite
numbers must satisfy the fixed tolerances. Generation timestamps and ZIP/JSON
byte identity are not financial equality requirements.

Capture uses the calculation's in-memory portfolio and FX selection rather than
rereading mutable workspace inputs. `aggregate` retains its ordinary JSON output.
A strict-quality calculation failure does not create a bundle. A successful
non-strict calculation may exclude holdings or have missing FX; those warnings
are preserved. `status: reproduced` means the captured result matched, including
its limitations; it does not establish complete history or valuation coverage.

Replay verifies all payloads and internal references, checks the method and
environment, validates the FX base currency and dated source evidence, calculates
again, and compares the result before publishing a fresh
restore directory. Write failures remove the staged workspace. The restored
directory contains the captured payloads and outer manifest. FX selection lives
in the run manifest; this is an analysis archive, not a copy of all mutable
workspace history. Use the bundle for repeat replay into another fresh directory.

The first slice supports aggregate only. It does not capture historical returns,
income plans, market series, report rendering, importer environments or original
statements. Bundles contain private normalized portfolio evidence and source
references; there is no redacted sharing mode yet. Checksums detect inconsistency,
not authorship or malicious replacement of an entire bundle.

### Compatibility and migration

- Existing v1 bundles remain verifiable and importable without conversion.
- `export` and `import-export` retain their v1 data archival/import behavior.
- v2 requires the new reader. `import-export` rejects v2 with a pointer to
  `replay-export`, so it cannot silently discard the run/result evidence.
- There is no automatic v1-to-v2 migration: v1 lacks the actual calculation state.
  Import v1 data and explicitly run `aggregate --bundle` to capture a new analysis.
- Unknown bundle/run/method versions, incompatible runtimes, missing or altered
  payloads, changed financial results, and existing restore destinations fail
  without publishing a restored workspace or fetching substitutes.

## See also

- [CLI reference: export / import](cli.md#export--import-bundles)
- [Storage layout](storage-layout.md)
