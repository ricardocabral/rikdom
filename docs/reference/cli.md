# CLI Reference

`rikdom` exposes a single CLI entrypoint with subcommands for the canonical
flows. This page lists each command, its primary flags, and the make
shortcut where one exists. Run `uv run rikdom <command> --help` for the
authoritative flag list.

Most commands accept these workspace flags:

- `--data-dir` (default `data`): workspace root.
- `--out-root` (default `out`): generated artifacts root.
- `--portfolio-name` (multi-portfolio mode): selects a registered portfolio.
- `--registry`: explicit path to a portfolio registry file.

## Workspace setup

| Command                                   | Make shortcut | Purpose                                                         |
| ----------------------------------------- | ------------- | --------------------------------------------------------------- |
| `rikdom workspace init --data-dir data`   | —             | Initialize a multi-portfolio registry with isolated data paths. |
| `rikdom workspace list --data-dir data`   | —             | List registered portfolios.                                     |
| `rikdom workspace rollup --data-dir data` | —             | Cross-portfolio rollup.                                         |

## Validate, aggregate, snapshot

| Command                                           | Make shortcut           | Purpose                                                                                     |
| ------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------- |
| `rikdom validate --data-dir data --out-root out`  | `make validate`         | Schema + structural validation + reconciliation.                                            |
| `rikdom validate --portfolio <path>`              | `make validate-fixture` | Validate a specific portfolio file.                                                         |
| `rikdom aggregate --data-dir data --out-root out` | `make aggregate`        | Aggregate by asset class.                                                                   |
| `rikdom snapshot --data-dir data --out-root out`  | `make snapshot`         | Append a historical snapshot with FX lock. See [FX snapshot fields](fx-snapshot-fields.md). |

`snapshot` flags:

- `--no-fx-auto-ingest` — disable automatic FX ingestion (history lookup only).
- `--fx-history <path>` — use a custom FX history file.
- `--rotate-bytes <N>` — rotate `data/snapshots.jsonl` when it exceeds N bytes.

## Performance

| Command                                                                         | Make shortcut       | Purpose                                                                                         |
| ------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------- |
| `rikdom performance --since <date> --until <date>`                              | `make performance`  | Modified-Dietz TWR + XIRR MWR over the window. See [performance output](performance-output.md). |
| `rikdom funded-ratio --portfolio data/portfolio.json --policy data/policy.json` | `make funded-ratio` | Deterministic funded-ratio projections for policy objectives.                                   |

Defaults: `--since` falls back to the earliest snapshot, `--until` to the
most recent.

`funded-ratio` uses the current portfolio aggregate, `policy.objectives[]`,
`cashflow_policy.contributions[]`, retirement spending assumptions, and real
return assumptions. Pass `--as-of YYYY-MM-DD` to pin the projection start date.

## Visualization

| Command                                                             | Make shortcut                 | Purpose                                                    |
| ------------------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------- |
| `rikdom visualize --data-dir data --out-root out --include-current` | `make visualize` / `make viz` | Render `out/dashboard.html` + `out/portfolio-report.html`. |

## Plugins

| Command                                                             | Make shortcut        | Purpose                                                                                                         |
| ------------------------------------------------------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------- |
| `rikdom plugins list --plugins-dir plugins`                         | `make plugins-list`  | Discover installed plugins.                                                                                     |
| `rikdom plugin init <name> --dest plugins`                          | —                    | Scaffold a new plugin from the bundled SDK template. See [first plugin tutorial](../tutorials/first-plugin.md). |
| `rikdom import-statement --plugin <name> --input <file> --dry-run`  | —                    | Preview an import.                                                                                              |
| `rikdom import-statement --plugin <name> --input <file> --write`    | `make import-sample` | Import a statement and write to `data/portfolio.json`.                                                          |
| `rikdom render-report --plugin quarto-portfolio-report`             | `make render-report` | Render a report through an `output` plugin.                                                                     |
| `rikdom storage-sync --plugin duckdb-storage --plugins-dir plugins` | `make storage-sync`  | Mirror canonical state to a `state/storage` backend.                                                            |

## External data connectors

| Command | Purpose |
| --- | --- |
| `rikdom connector describe --plugin <name>` | Describe a selected connector's declared operations and parameters. Offline by plugin contract. |
| `rikdom connector query --plugin <name> --operation <operation> --params '<json>'` | Query one declared operation and print JSON with acquisition provenance. |

Connector flags:

| Flag | Applies to | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `--plugin` | Both | Yes | — | Name of an installed `external/connector` plugin. |
| `--plugins-dir` | Both | No | `plugins` | Directory containing plugin folders and manifests. |
| `--operation` | `query` | Yes | — | Operation name advertised by the selected connector. |
| `--params` | `query` | No | `{}` | JSON object; accepted fields and required inputs belong to the plugin. |

These commands do not accept workspace flags or load portfolio files.
Authentication and endpoint configuration belong to each plugin; there is no
generic token or endpoint flag in the connector CLI. Consult the selected
plugin's README for its configuration and available operations.

`describe` returns a descriptor with `contractVersion`, `readOnly`, and
`operations`. `query` returns `contractVersion`, `plugin` (name, implementation
version, API version), `operation`, `retrievedAt`, and raw provider JSON under
`data`. Provider `null` values, warnings, and errors remain in that payload.
The envelope format is defined in the [connector hook reference](plugin-hooks.md#connector-hooks).

Successful commands exit with status `0`. Invalid parameters, unsupported
operations, plugin-loading failures, and handled provider failures exit with
status `1`, with a diagnostic on stderr. Provider errors embedded in a
successful JSON response remain under `data`; callers must inspect them.
Argument parsing failures exit with status `2`.

For the workflow see [query external data](../how-to/query-external-data.md).
Plugin-owned REST and MCP clients use the same CLI contract.

## Migrations

| Command                                                     | Make shortcut                 | Purpose                               |
| ----------------------------------------------------------- | ----------------------------- | ------------------------------------- |
| `rikdom migrate --portfolio data/portfolio.json --dry-run`  | `make migrate-dry-run`        | Preview portfolio migration plan.     |
| `rikdom migrate --portfolio data/portfolio.json`            | —                             | Migrate in place with sibling backup. |
| `rikdom migrate-policy --policy data/policy.json --dry-run` | `make migrate-dry-run-policy` | Preview policy migration plan.        |
| `rikdom migrate-policy --policy data/policy.json`           | —                             | Migrate policy in place.              |

Migration flags: `--to <version>`, `--output <path>`, `--no-backup`. See
[run a migration](../how-to/run-a-migration.md).

## Export / import bundles

| Command                                        | Make shortcut | Purpose                             |
| ---------------------------------------------- | ------------- | ----------------------------------- |
| `rikdom export --output out/rikdom-export.zip` | —             | Build a `rikdom-export` ZIP bundle. |
| `rikdom verify-export --bundle <zip>`          | —             | Verify checksums without applying.  |
| `rikdom import-export --bundle <zip>`          | —             | Import a verified bundle.           |

Bundle layout and checksum manifest: [export format reference](export-format.md).

## Compaction

| Command                                                     | Purpose                                         |
| ----------------------------------------------------------- | ----------------------------------------------- |
| `rikdom compact --snapshots data/snapshots.jsonl --dry-run` | Plan a compaction (no write).                   |
| `rikdom compact --snapshots data/snapshots.jsonl`           | Apply with `<journal>.bak` safety net.          |
| `rikdom compact --rotate --rotate-bytes <N>`                | Rotate aside, then compact the new active file. |

Default retention: keep all rows < 30 days, weekly buckets 30 days–1 year,
monthly buckets > 1 year. See [storage durability](../explanation/storage-durability.md).

## Common workflows

```bash
# Bootstrap a fresh workspace
make sync && make bootstrap && make validate

# Daily flow
make snapshot && make visualize

# Run against an alternate workspace
make validate DATA_DIR=workspace-data OUT_DIR=workspace-out PORTFOLIO_NAME=paper
```

## See also

- [Tutorials](../tutorials/) — guided walkthroughs.
- [How-to guides](../how-to/) — task-oriented recipes.
