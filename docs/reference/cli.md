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

- `--fx-provider <plugin>` — explicitly enable the selected connector for missing FX (`daily-rates` operation). Without it, snapshot uses local history only.
- `--no-fx-auto-ingest` — disable acquisition even when a provider is selected.
- `--fx-history <path>` — use a custom FX history file.
- `--rotate-bytes <N>` — rotate `data/snapshots.jsonl` when it exceeds N bytes.

## Performance

| Command                                                                         | Make shortcut       | Purpose                                                                                         |
| ------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------- |
| `rikdom performance --since <date> --until <date>`                              | `make performance`  | Linked TWR or disclosed Dietz fallback + XIRR MWR over the window. See [performance output](performance-output.md). |
| `rikdom funded-ratio --portfolio data/portfolio.json --policy data/policy.json` | `make funded-ratio` | Deterministic funded-ratio projections for policy objectives.                                   |

Defaults: `--since` falls back to the earliest snapshot, `--until` to the
most recent.

Optional portfolio calculation inputs, also accepted by `viz`:

| Flag | Meaning |
| --- | --- |
| `--historical-valuations CONFIG` | Replace recorded calculation snapshots with explicit full-position price/FX replay; no partial-total fallback. |
| `--historical-fx CONFIG` | Convert external cashflows and benchmarks with dated local FX. |
| `--flow-valuations JSON` | Explicit pre/post external cashflow valuations for linked TWR. |
| `--profit-basis JSON` | Reviewed FIFO opening lots, period history and bookend position/cash evidence. |
| `--policy JSON`, `--benchmarks-dir DIR` | Resolve selected policy benchmarks using local series. |

`--historical-valuations` and `--profit-basis` require `--by portfolio`.
`--flow-valuations` also supports portfolio scope only. Missing price/FX data
produces explicit unavailable JSON (exit 0) in `performance`; malformed sidecars
produce a stderr diagnostic (exit 1). In `viz`, invalid calculation inputs make
the performance section unavailable while retaining other report sections. Invalid/incomplete reviewed cost evidence produces
an unavailable decomposition with diagnostics. See [offline replay and profit](../how-to/replay-performance-data.md).

`funded-ratio` uses the current portfolio aggregate, `policy.objectives[]`,
`cashflow_policy.contributions[]`, retirement spending assumptions, and real
return assumptions. Pass `--as-of YYYY-MM-DD` to pin the projection start date.

## Income

`rikdom income` reads the effective activity ledger and reports posted dividends
and interest, grouped by calendar month/year and native currency. It runs offline.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--portfolio <path>` | Resolved workspace portfolio | Canonical JSON input. |
| `--start YYYY-MM-DD` | Unbounded | Inclusive first calendar date. |
| `--end YYYY-MM-DD` | Unbounded | Inclusive last calendar date. |
| `--income-plan <path>` | Embedded `extensions.rikdom_income_plan`, if present | Local versioned announcements, estimates, reviewed payment links, and declared cost bases. An explicit file takes precedence. |
| `--out-dir <path>` | `<out-root>/reports[/<portfolio-name>]` | Artifact destination. |
| `--format json\|markdown\|both` | `both` | Selects `income.json`, `income.md`, or both. |

Standard workspace flags select the data/output roots, registry and portfolio.
Successful execution returns status `0` and prints the full report as JSON,
regardless of artifact format. Invalid report inputs return status `1` with a diagnostic
on stderr before report writes; argument parsing errors return status `2`. Missing inputs are not bootstrapped by this
command. Canonical files and import logs are not modified.

With a plan, JSON additionally includes `planning` version `1`, containing
`announced`, `estimates`, `reconciliation`, `yield_on_cost`, and `diagnostics`.
Received `events`, `monthly`, and `yearly` amounts retain their actual-ledger
meaning. Announcements and estimates never enter these totals. Markdown renders
the planning results in separate sections. The plan is validated by the income
calculation before artifact writes; output filenames cannot overwrite either
the portfolio or an explicit plan input, including existing symlink or hard-link
aliases. Markdown retains each planning scope and source evidence; yield rows
also retain the declared income source and coverage. Existing commands without
a plan keep their original version `1` JSON output contract.

See the [income plan reference](income-plan.md) for exact required source, scope,
revision, linkage and cost-method fields, and the
[local sample workflow](../how-to/summarize-income.md#compare-announcements-with-actual-payments).
Payment links resolve effective corrections and do not infer receipt from an
announcement or a reinvestment purchase. Yield `ratio` is a fraction (`0.05`
means `5%`) for its declared period and amount basis, never silently annualized.
Unsupported or missing inputs return an unavailable result with its reason.

Output version `1` includes `start`, `end`, `date_convention`, `limitations`,
`diagnostics`, `events`, `monthly` and `yearly`. Each event retains its activity ID,
event type, date, currency, asserted account/holding/asset-type/instrument
references, amount basis and nullable `gross`, `withholding`, `fees`, and `net`.
Missing references remain `null`. Each period/currency bucket contains
`event_count` and one object per monetary metric:

- `total`: complete sum, or `null` if any event's amount is unavailable.
- `known_subtotal`: sum of available amounts, including signed adjustments.
- `unavailable_count`: events without a usable amount for that metric.

The reporting date is the calendar day in `effective_at` at its explicit offset,
without conversion to UTC. It does not assert actual cash availability. Different
currencies are never combined. Corrections are projected before filtering;
cancelled/pending events, buys, transfers, principal returns and generic `income`
are excluded from received dividends/interest. Generic-income exclusions produce
a diagnostic counted across the effective history, even outside the date filter.
Each ledger activity must have a unique nonempty ID and an explicit valid status;
any supplied idempotency keys must also be unique and nonempty. An empty history
does not establish complete statement coverage.

Income metadata uses an optional versioned declaration:

```json
"metadata": {"rikdom_income": {"version": 1, "amount_basis": "net"}}
```

`amount_basis` is `gross`, `net`, or `unknown`. Without the declaration, the
existing schema convention treats `money` as gross. The older generic marker
`metadata.amount_basis: "reported_gross_net_unknown"` means unknown when no modern
marker is present. A modern declaration takes precedence. Unknown basis leaves
both gross and net unavailable.

For gross money, net is gross minus declared same-currency withholding and fees.
For net money, gross is net plus those charges. Missing withholding prevents this
derivation; explicit zero withholding is known. Absent fees are reported as
unavailable and no undeclared fee is applied. Cross-currency charges prevent
derivation; they are not converted with current FX. Separately posted tax events
are not matched to payments. These conventions also prevent net-marked
instrument-return receipts from having their charges deducted twice; explicitly
unknown distribution basis makes full instrument returns unavailable.

See [summarize income](../how-to/summarize-income.md) for usage and import limits.

## Visualization

| Command                                                             | Make shortcut                 | Purpose                                                    |
| ------------------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------- |
| `rikdom viz --data-dir data --out-root out --include-current` | `make viz` | Render `out/dashboard.html` + `out/portfolio-report.html`. |

`visualize` and `render-report` (and their make targets) are deprecated
compatibility aliases for `viz`. Use `--plugin` to select an output plugin.
Explicit `viz --benchmarks-dir` overrides an embedded policy's benchmark directory;
without that flag, its configured directory remains in use. Built-in report
output paths must not alias selected inputs or their local cache dependencies,
including inside the generated Quarto asset trees.

## Plugins

| Command                                                             | Make shortcut        | Purpose                                                                                                         |
| ------------------------------------------------------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------- |
| `rikdom plugins list --plugins-dir plugins`                         | `make plugins-list`  | Discover installed plugins.                                                                                     |
| `rikdom plugin init <name> --dest plugins`                          | —                    | Scaffold a new plugin from the bundled SDK template. See [first plugin tutorial](../tutorials/first-plugin.md). |
| `rikdom import-statement --plugin <name> --input <file> --dry-run`  | —                    | Preview an import.                                                                                              |
| `rikdom import-statement --plugin <name> --input <file> --write`    | `make import-sample` | Import a statement and write to `data/portfolio.json`.                                                          |
| `rikdom viz --plugin quarto-portfolio-report`                       | `make viz`           | Render reports through an `output` plugin.                                                                     |
| `rikdom storage-sync --plugin duckdb-storage --plugins-dir plugins` | `make storage-sync`  | Mirror canonical state to a `state/storage` backend.                                                            |

## Normalized local enrichment

`rikdom enrichment --plugin local-market-series --request request.json` reads a
strict version 1.0 request and prints normalized data plus host-selected lookup
evidence. `--plugins-dir` defaults to `plugins`. It accepts no workspace flags,
loads no portfolio and writes no canonical files. Missing/stale lookups are
successful JSON results; malformed requests, invalid provider data or loading
errors exit 1 with stderr; argument errors exit 2.

`rikdom plugin init NAME --type enrichment --dest plugins` scaffolds an
executable API 1.2 local provider and its tests/contract fixtures. The default
`--type source/input` preserves the existing importer scaffold. See the
[enrichment contract](enrichment.md).

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
make snapshot && make viz

# Run against an alternate workspace
make validate DATA_DIR=workspace-data OUT_DIR=workspace-out PORTFOLIO_NAME=paper
```

## See also

- [Tutorials](../tutorials/) — guided walkthroughs.
- [How-to guides](../how-to/) — task-oriented recipes.

## Import trust and manual corrections

`import-statement --reconcile --write` writes the normal import and the four
trust artifacts under `<out-root>/reports/`. Preview includes candidate summaries
but creates no artifacts/log/canonical writes. `--fx-history` selects cached inputs.
See [import diagnostics](import-diagnostics.md) for coverage and blocking codes.

`activity correct <id> --input <complete-activity.json> --reason <text>` previews
an immutable replacement. `--write` applies; `--dry-run` overrides `--write`;
`--reconcile` adds trust artifacts. Workspace flags, `--import-log`,
`--import-run-id`, `--ingested-at`, `--fx-history`, and `--plugins-dir` apply.
The first correction writes schema 2.0.0 with the linked event atomically.
Uncorrected 1.x files remain supported. Older raw-ledger calculators are unsafe
for correction-bearing data.

`viz --plugin <name> --plugins-dir <dir>` selects an output plugin explicitly.

## `market-series`

Read a versioned local price/FX input without writing files:

```bash
uv run rikdom market-series --input data-sample/market-series.json \
  --series example-price --as-of 2026-01-03T16:00:00Z --max-age-seconds 86400
```

Required options: `--input`, `--series`, `--as-of` (UTC timestamp), and
`--max-age-seconds` (finite nonnegative effective age, inclusive).
`--retrieved-before` optionally limits the inclusive retrieval timestamp for
historical knowledge replay; omission uses all vintages in the file.

Prints stable JSON with `available`, `missing`, or `stale` status and selected
observation, source, license, and revision provenance. Missing/stale queries exit
0; invalid input exits 1. Check status before consuming a value. See the complete
[contract and offline replay recipes](market-series.md).

### Historical FX for performance

`performance --historical-fx CONFIG` reads [local dated FX](historical-fx.md) for
external cashflows and [benchmark comparisons](benchmark-fx.md). Missing or stale
rates make affected metrics unavailable; `--by instrument` is unsupported.
