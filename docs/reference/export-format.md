# Rikdom Export Bundle Format

A `rikdom-export` bundle is a ZIP file for archival and interchange. It
stores canonical rikdom data files plus a checksum manifest that importers
verify before writing anything.

## Layout

```text
rikdom-export.zip
├── rikdom-export.json
└── data/
    ├── portfolio.json
    ├── snapshots.jsonl      # optional
    ├── fx_rates.jsonl       # optional
    └── policy.json          # optional
```

## Manifest

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

## See also

- [CLI reference: export / import](cli.md#export--import-bundles)
- [Storage layout](storage-layout.md)

## Captured analysis extension (v2)

`export`, `import-export`, and existing v1 files retain their canonical-data
contract. `export-analysis` writes version `2.0.0` using the same ZIP manifest and
size/SHA-256 verification. Current readers verify either version; older readers
reject v2 explicitly. `import-export` directs v2 users to `restore-analysis` and
makes no canonical writes. No v1 migration is required.

A v2 archive contains `analysis/analysis-run.json` (`analysis_manifest`) and
`analysis/<relative-path>` entries (`analysis_file`). Multiple analysis files
are allowed; paths and ZIP members must be unique. Restoration never extracts
arbitrary archive paths or executes bundled Python. It verifies all archive
payloads, validates the run and compatible environment, then publishes a new
directory. Existing directories are refused; failures preserve previous runs.

The run manifest is `rikdom-analysis-run`, version `1.0`, operation `performance`.
It records copied input roles, relative paths, sizes, SHA-256 hashes, parameters,
selected methods, expected `result.json` hash, and environment evidence. Portfolio,
snapshots, policy, flow valuations, profit basis, and dated market caches retain
their input bytes. Historical FX/valuation configuration rewrites only the local
`market_series_file` reference and records its original-byte hash as well as the
portable config hash. Copied caches preserve all revisions, cutoffs, coverage,
source and license metadata. Referenced leaf benchmark files (including composite
components) are copied; unrelated files and original statements are excluded.
Malformed/duplicate-key/nonfinite JSON and torn or malformed JSONL are refused;
JSONL must end in a newline, matching the journal reader's complete-record rule.

See [capture and replay instructions](../how-to/capture-and-replay-analysis.md).
