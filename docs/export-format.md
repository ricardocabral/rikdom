# Rikdom Export Bundle Format

A `rikdom-export` bundle is a ZIP file for archival and interchange. It stores canonical rikdom data files plus a checksum manifest that importers verify before writing anything.

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

Import supports workspace path options (`--data-dir`, `--portfolio-name`, `--registry`) and writes `.bak-<timestamp>` backups for overwritten files unless `--no-backup` is supplied.
