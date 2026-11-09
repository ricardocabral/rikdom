# External-agent read contract

External agents consume Rikdom's local records, CLI JSON and Python calculations.
There is no required agent server, model runtime or new context protocol. This
reference connects the existing surfaces; [use portfolio context](../how-to/use-portfolio-context.md)
gives the working procedure.

## Evidence surfaces

| Surface | Meaning and evidence to retain |
| --- | --- |
| `portfolio.json` | Accepted local state: holdings, activity ledger, optional lots, liabilities and statement observations. Retain `schema_version`, `schema_uri`, selected file identity and relevant entity IDs. Canonical acceptance does not prove real-world completeness. |
| `policy.json` (optional) | User intent, account catalog, objectives, allocation targets, assumptions and guardrails. Its `schema_version` is independent of the portfolio's. Cite `identity.portfolio_id`, `identity.policy_id`, applicable sections and provenance when present. A policy assumption is not a source observation. |
| `statement_observations[]`, entity provenance and `source_ref` | Provider observations, source document paths/digests, report periods, page/table evidence and ingestion provenance when supplied. An older statement valuation does not replace a current holding valuation merely because it was imported later. Original statement files are not implicitly captured. |
| `extensions.rikdom_reviewed_imports` | Version `1` retained source/review/effective projections. Decisions identify provider, collection, entity, version, evidence, source baseline and accepted-source baseline. `revisions[]` retains accepted states; it does not reconstruct history before tracking began. |
| `extensions.rikdom_import_diagnostics.statements` | Per-statement coverage declarations and unsupported-event evidence. `import_log.jsonl` additionally retains successful import/correction audit information. Logs are not a replacement for the effective portfolio. |
| `snapshots.jsonl` | Historical aggregated values with timestamps, base currency, optional account/bucket totals and FX evidence. They are recorded valuations, not automatically verified historical positions or cashflow boundaries. |
| `fx_rates.jsonl`, local market-series files and calculation sidecars | Explicit conversion, valuation, flow-boundary and reviewed cost evidence. Each has its own contract and coverage limits. Separate files must be selected and captured explicitly. |
| Calculation results and captured runs/bundles | Derived results over the selected inputs and parameters. Preserve methods, currency, actual dates, warnings and unavailable fields together with the numbers. A reproduced result retains its original limitations. |

See [storage layout](storage-layout.md), [schemas](schemas.md),
[reviewed imports](reviewed-imports.md), [import diagnostics](import-diagnostics.md)
and [export format](export-format.md) for full shapes. Unknown extension data and
unsupported source evidence remain evidence: preserve them when copying records;
do not interpret unfamiliar fields as permission to drop them or claim coverage.
An unsupported contract/version must be reported, not silently coerced.

## Identities and versions are separate

Portfolio `schema_version` describes a document contract, not a revision counter.
Uncorrected compatible 1.x portfolios and correction-bearing `2.0.0` portfolios
have different ledger semantics. Readers must use the supported correction
projection; summing raw original and replacement activities double-counts events.
Policy versions, review integer versions and market `contract_version: "1.0"`
belong to separate tracks. See [migrations](migrations.md).

Ordinary aggregate/performance JSON does **not** carry one universal result-schema
version. Record the installed core/environment and relevant output contract;
do not invent `result_version` or equate a bundle version with a result version.

| Capture | Outer bundle | Inner run and method | Input/result references |
| --- | --- | --- | --- |
| Performance: `capture-analysis`, then `export-analysis` | `rikdom-export`, `format_version: "2.0.0"` | `analysis-run.json` (archive path `analysis/analysis-run.json`): `format: "rikdom-analysis-run"`, `format_version: "1.0"`, `operation: "performance"`. `methods` records selected return methods/bases; there is no aggregate-style `method.version`. | `inputs` maps roles to relative paths. `files` maps paths to `sha256`, `bytes`, `role` and, for selected original inputs, `original_sha256`. `output_sha256` identifies `result.json`. |
| Aggregate: `aggregate --bundle` | `rikdom-export`, `format_version: "3.0.0"` | `analysis/run.json`: `format: "rikdom-analysis-run"`, `format_version: "1.0.0"`, `method: {"name": "aggregate", "version": "1.0.0"}`. | `inputs.portfolio` and `result` contain path/hash objects. Parameters retain `strict`, `fx_lock` and `fx_warnings`; `equality` specifies numeric tolerances. |

Archival `export` bundles remain version `1.0.0` and do not capture a calculation.
Dispatch by the actual format/version and operation/method; v2 performance and v3
aggregate manifests are not interchangeable. Performance replay checks canonical
JSON result hashes; aggregate replay uses absolute tolerance `1e-8` and relative
tolerance `1e-12`, with matching structure and diagnostics. Both require compatible
installed trusted environments and never install or execute bundled code.

Hashes identify evidence under their stated convention. Bundle/file SHA-256
checks establish byte consistency against the manifest, not schema validity,
source authenticity, authorship or financial completeness. Reviewed-import
`source_revision` is a semantic source hash that ignores processing details;
`source_payload_hash`, where present, identifies the exact retained normalized
source serialization. Revision `content_hash` includes source facts, effective
state and reviews. These are not interchangeable with a raw file hash or a
universal portfolio revision. Cite the revision's `version` and hash names
explicitly. A manually edited portfolio may have no corresponding retained review
revision; capture/hash the actual selected document as well.

## Scope, currency and time

Workspace selection (`--data-dir`, optional `--portfolio-name`/`--registry`) and
explicit file overrides determine the portfolio read. Record resolved paths and
registry selection where relevant; do not combine different registered portfolios
or silently include another workspace. Names, provider account identifiers and
tickers do not establish account/entity identity.

`settings.base_currency` is the reporting currency for aggregation and portfolio,
account and strategic-bucket performance. Preserve original Money currencies and
FX evidence too. Policy `identity.policy_base_currency` is declared intent, not
an instruction to silently convert a result. Instrument returns use native
transaction currency and require unique holding selection.

Holdings/activities use explicit `account_id`; policy `accounts[].account_id`
supplies the account catalog. Unassigned amounts remain `__unassigned__`.
`aggregate` values the selected portfolio's holdings and exposes `by_account`;
`performance --by account` adds scoped rows using snapshot account totals and
account flows. Its top-level portfolio result remains portfolio-wide. Bucket
performance uses snapshot bucket totals and asset-class cashflow attribution;
unallocated evidence remains `__unallocated__`. These are not arbitrary filters
that establish a new complete ledger. Valid internal cash pairs are suppressed
only at the portfolio boundary; account calculations retain crossing flows.

| Time evidence | Meaning |
| --- | --- |
| Holding `as_of`, valuation `price_as_of`, activity `effective_at`/`trade_at`/`settled_at`, statement period/balance dates | When a position, price, transaction or source report applies. Timing bases are not interchangeable. Missing timing stays unknown. |
| Snapshot `timestamp`; result `period_start`/`period_end` | Actual valuation instants and selected calculation window. Requested `since`/`until` can differ from selected bookends; cite both. |
| Market observation `effective_at` and `retrieved_at` | Market time versus when that vintage was acquired/entered. `retrieved_before` limits eligible knowledge; absence permits later corrections already present in the file. |
| Ingestion `ingested_at`, source envelope `generated_at`, policy provenance timestamps | Processing/declaration history where present; none substitutes for an economic effective date. |
| Run `created_at`, performance `parameters.analysis_as_of`, aggregate `parameters.fx_lock.snapshot_timestamp` | Capture/calculation and FX-selection context. `analysis_as_of` pins legacy FX selection, not the return window or source retrieval time. |

An agent should record its own read time separately when reporting a live-file
read. No universal retrieval/calculation timestamp exists in every source/result;
disclose absence instead of deriving it from file modification time. Staleness is
relative to an explicit query and age rule, not automatically relative to today.

## Stable selection across files

`capture_performance_run(output, *, inputs, parameters=None)` in
`rikdom.analysis_runs` copies selected local inputs into a private staging
directory, calculates using those copies, and publishes a new run directory.
CLI `capture-analysis` uses this path. Existing destinations are refused.
Subsequent analysis should read the captured manifest, copied inputs and
`result.json`, rather than join the result to newer live files.

Copying is sequential across files, including nested market caches and referenced
benchmark leaves. The operation does **not** lock the live workspace or promise
an atomic multi-file snapshot. Atomic publication means a completed run appears
together; it does not mean all source files were observed at one instant. Select
a quiescent workspace, a separately coordinated filesystem snapshot, or a known
consistent copied file set before capture. If that cannot be established, report
the consistency limitation and recapture after writes stop. Rechecking hashes can
detect changes; it cannot alone prove cross-file economic consistency.

Performance captures only selected inputs: portfolio, snapshot/FX journals and
optional policy, referenced benchmark leaves, historical FX/valuation configs and
their market caches, flow valuations and profit basis. Nested config paths are
rewritten for portability with original-byte hashes retained. API omissions of
snapshot/FX journals become explicit empty captured journals; the CLI expects its
resolved files to exist. Import logs and original statements are not implicitly
included. Additional source evidence must be preserved and identified separately.

`aggregate --bundle` instead captures the calculation's actual in-memory portfolio,
selected FX lock and result. It does not reread the portfolio for capture and does
not archive the entire FX history or policy. This also supplies no atomic
live-workspace snapshot guarantee. Verified v2/v3 bundles can be reproduced into
fresh directories with `replay-export`; redacted/omitted v2 evidence is explicitly
non-replayable. See [capture and replay](../how-to/capture-and-replay-analysis.md).

## Completeness and uncertainty

There is no universal status enum across these surfaces. Preserve the literal
status, its scope, diagnostics and evidence; a plain-language qualification must
not broaden its meaning.

| Interpretation | Existing representation and limit |
| --- | --- |
| Complete | Import `history_coverage[].status: "complete"` is a scoped source declaration. Performance `fx_status: "complete"` covers required cashflow conversions; it does not verify snapshot FX. `growth_bridge.status: "complete"` only reconciles supplied arithmetic, as stated by `completeness_scope` and `caveat`. Instrument `status: "complete"` uses its independent history/valuation gates. |
| Approximate | `twr_method: "modified_dietz"`, legacy `twr_pct`, `fx_status: "legacy_approximate"`, fallback reasons and warnings disclose approximations. `twr_return_pct` is the selected method's period return; `mwr_pct` is annualized XIRR. Legacy foreign-flow conversion or unresolved transfer identity cannot establish exact linked TWR. |
| Unavailable | `twr_method: "unavailable"`, null returns, bridge `status: "unavailable"`, FX/valuation/profit component statuses and reasons are local to those components. Instrument `incomplete_history` and quantity `not_computable` express other supported limits. Preserve known observations even when full results are unavailable. |
| Missing | Market lookup `status: "missing"` retains reasons such as `unknown_series` or `no_eligible_observation`. Missing files may instead fail the command. Aggregate trust records identify exclusions such as `missing_market_value` and `fx_missing`; totals can therefore be partial. |
| Stale | Market lookup `status: "stale"` with `maximum_age_exceeded` retains the selected observation and its age. Historical FX/valuation calculations propagate failed lookups into unavailable results. Ordinary current aggregation does not impose a universal holding-age rule. |
| Disputed | Reviewed-import preview `preflight.review.conflicts[]` and `ok: false` expose contradictions and block writes pending revision-bound resolution. There is no universal stored `status: "disputed"`. Accepted canonical state remains separate from the rejected incoming assertions. |

Import coverage also supports `partial` and `unknown`. Quantity reconciliation
uses `matched`, `mismatched`, `not_computable`; a match is not proof of a complete
financial history. Empty `unsupported_events` means none observed in that input,
not universal importer support. Retain unsupported source rows/references and
unknown coverage; do not remove them to make a result look complete.

Never translate unknown, missing, excluded or unavailable into zero or confirmed
absence. Some existing compatibility outputs contain numeric placeholders:
performance without bookends returns zero start/end values alongside warnings and
null returns; account/bucket calculations may treat an absent snapshot key as
zero and explicitly warn. Those conventions are not evidence of a zero balance.
Non-strict aggregate can skip unvalued/unconvertible holdings; Python
`AggregateResult.trust_records` and reconciliation artifacts expose exclusions.
The compact aggregate CLI JSON does not expose every trust record, so a warning-free
total alone cannot certify valuation completeness. Exit status zero means command
execution succeeded: missing/stale market lookups and financially unavailable
performance can still exit zero.

## Calculation and write boundaries

Use `rikdom.aggregate.aggregate_portfolio` for shared valuation and diagnostics;
use `rikdom.performance.compute_performance` with
`performance_result_to_dict` for its shared portfolio return/bridge contract.
The CLI additionally assembles calendar rows and optional historical valuation
and profit evidence. See [performance output](performance-output.md),
[historical valuation](historical-valuation.md), [profit attribution](profit-attribution.md)
and [calculation trust](../explanation/calculation-trust.md). Do not independently
reimplement ledger correction, cashflow or FX semantics inside an agent.

Reasoning output is a proposal until explicitly accepted. It never automatically
writes source observations, accepted reviews, policy, activities or valuations.
The supported routes remain:

- New/source evidence: normalized `import-statement` preview, then an explicitly
  authorized `--write` after validation/preflight; preserve stable IDs/provenance.
- Reviewed mappings/coverage: `import-statement --review-file` with explicit
  evidence. Conflicts require the exact preview source revision and an explicit
  `keep_review` or `accept_source` resolution. Retained review history is not edited
  in place to simulate acceptance.
- Ledger correction: `activity correct <id> --input <complete replacement> --reason
  <text>` preview, followed by authorized `--write`. Originals remain in the audit
  ledger; dependent lots/corporate actions have documented restrictions.
- Policy changes: user-reviewed policy-file authoring, validated with
  `rikdom.policy.validate_policy`, or the existing
  [define-policy workflow](../../.codex/skills/define-policy/SKILL.md).
  `migrate-policy --dry-run` previews schema upgrades; migration is not acceptance
  of a new investment assumption. There is no general policy-write CLI command.

See [entry and correction](../how-to/enter-and-correct-activities.md) and
[reviewed imports](reviewed-imports.md). A proposal should name the current input
hash/revision, target IDs/fields, proposed value, source or user-declaration
evidence, uncertainty, and the preview/write route. Keep it separate from the
captured evidence and recalculate after an accepted change.
