# Storage Layout

Rikdom stores all canonical state in plain-text files inside a workspace
directory (default `data/`). For the durability rules, see
[storage durability](../explanation/storage-durability.md).

## Workspace files

| File | Kind | Written by | Purpose |
| --- | --- | --- | --- |
| `data/portfolio.json` | Whole doc | `import-statement --write`, `activity correct --write`, `migrate` | Current portfolio truth. |
| `data/snapshots.jsonl` | Append-only JSONL | `snapshot` | Historical aggregated values. |
| `data/import_log.jsonl` | Append-only JSONL | Successful import/correction writes | Import audit trail. |
| `data/fx_rates.jsonl` | Append-only JSONL | `snapshot --fx-provider <plugin>`, manual edits | FX history used at snapshot time. |
| `data/policy.json` | Whole doc | `migrate-policy`, manual edits | Investment Policy Statement (optional). |
| `data/income-plan.json` (example path) | Whole doc | User-supplied local file | Optional announcements, estimates, reviewed payment links and declared cost evidence; pass the chosen path with `income --income-plan`. |
| `data/portfolio_registry.json` | Whole doc | `workspace init` | Multi-portfolio registry (optional). |
| `data/portfolios/<name>/` | Directory | Workspace mode | Per-portfolio isolated data files. |

`make bootstrap` copies the sample policy as well as the portfolio, snapshots,
FX history, and benchmarks. A custom policy can be authored manually or with the
`define-policy` skill; `migrate-policy` upgrades an existing file. The registry
is created explicitly by `workspace init`.

Income plan files are not created automatically: their path and contents
are supplied explicitly, and `income` never creates or updates the input plan.
The same plan object can instead be embedded in
`portfolio.extensions.rikdom_income_plan`; an explicit `--income-plan` file takes
precedence. Both forms use the independent integer plan `version: 1`, not the
portfolio's semantic `schema_version`. See the [income plan reference](income-plan.md)
and [schema design](../explanation/schema-design.md#optional-income-planning-evidence).

The income command writes only the requested JSON/Markdown report artifacts,
protects portfolio and plan inputs from output aliases, and leaves the actual
activity ledger, holdings, snapshots and import log unchanged. Announcements and
estimates do not become received cash or realized returns. Include any separate
plan file in a workspace backup yourself; the interchange bundle does not
automatically collect arbitrary sidecar paths. An embedded plan travels with
the portfolio document as extension data.

## Tracked starter templates

Commands using default resolved workspace inputs can seed missing
`portfolio.json`, `snapshots.jsonl`, and `fx_rates.jsonl` from their tracked
`data-sample/` counterparts. Only the input paths used by that command are
seeded. Import/correction previews and `income` do not bootstrap inputs.
Paths outside the resolved workspace defaults are not seeded from samples.
`data/` itself is gitignored.

## Schema files

`schema/*.json` carry the validation and interoperability contracts.
Documented in [schemas reference](schemas.md).

## Format choice

JSON + JSONL was chosen for:

- Ubiquitous tooling support (`cat`, `jq`, every language).
- Easy Git diff/merge for collaborative history.
- Survives framework/runtime churn — no proprietary serializers.
- Friendly to LLM ingestion and deterministic parsing.

## Backup

- Commit `schema/` and `data-sample/` updates to git when templates/contracts
  change.
- Optional periodic encrypted backups of local `data/`.
- Keep plugin import fixtures for auditability.

## See also

- [Storage durability](../explanation/storage-durability.md)
- [Schemas reference](schemas.md)
- [Recover from a crash](../how-to/recover-from-crash.md)
