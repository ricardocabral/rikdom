# Rikdom Roadmap: Free, Local, Global Portfolio Workflows

Reviewed on **2026-10-23** against the repository and Sigma Finance's public site/demo.
Priorities express delivery order, not release dates. Checked items identify existing
capabilities; unchecked items describe remaining work.

## Product direction

Give people the ability to consolidate investments, understand returns and income,
plan allocations, and simulate decisions **for free, on their own computer, with
control over their data**. Rikdom remains the open schema + CLI + calculation and
plugin foundation described in the [README](README.md). Reports and optional local
interfaces compose that foundation into usable workflows.

- **Free end-to-end path**: no subscription, mandatory account, paid AI service,
  or product-imposed holding/transaction limits for reference workflows. Hardware
  and data availability still constrain capacity. Community reference plugins must
  have open licenses and work with user-supplied files or locally cached data.
- **Local by default**: installed tools must import, calculate, report, simulate,
  and export offline. Fresh market data requires an explicit optional connection;
  providers may impose fees, quotas, redistribution terms, or coverage limits.
- **Global by contract**: currencies, exchanges, identifiers, calendars, language,
  asset definitions, and tax jurisdictions must not be hard-coded to Brazil/US.
  Regional packs add coverage without forking the core.
- **Security with an explicit trust boundary**: local storage alone does not imply
  encryption or plugin isolation. The current trusted, in-process Python runtime
  needs the safeguards and constrained execution work in Phase 5B.
- **User-controlled decisions**: calculations and proposed allocations must expose
  inputs, assumptions, versions, and data gaps. Rebalancing starts with reviewable
  simulations; brokerage order submission is outside this roadmap's parity scope.

## Sigma Finance review and fit

Sources: [features](https://sigmafinance.app/#features),
[coverage and import flow](https://sigmafinance.app/#coverage),
[plans](https://sigmafinance.app/#plans),
[performance demo](https://sigmafinance.app/performance?demo=1),
[income demo](https://sigmafinance.app/provents?demo=1),
[rebalance demo](https://sigmafinance.app/rebalance?demo=1), and
[historical simulator](https://sigmafinance.app/simulator).

This is a review of public descriptions and visible demo screens, not a validation
of Sigma's calculations or paid integrations. The simulator's configuration was
inspected, without executing a backtest. PRO+ showed a waitlist; automatic B3 sync
and IRPF/DARF assistance are advertised there, not verified as delivered.

| Sigma reference | Rikdom decision and placement |
| --- | --- |
| Consolidated holdings; Brazil/US assets and FX | High fit. Extend existing multi-portfolio valuation with regional catalog/provider packs; do not promise universal coverage (Phases 3, 5). |
| B3 trade-file import and manual entries | High fit. Preserve file-first imports; add trade-history coverage and a validated manual-entry workflow (Phase 3). |
| TWR/MWR, benchmarks, realized/unrealized profit, income, contributions | High fit. Build on existing Dietz/XIRR and benchmarks; add linked TWR, historical FX, profit decomposition, and report integration (Phase 4B). |
| Custom groups and target allocation | High fit. Extend existing policy buckets into saved views and a local rebalance planner (Phase 5A). |
| Paid/announced distributions and yield on cost | High fit. Separate observed, announced, and estimated income with explicit cost-basis conventions (Phase 4A). |
| Latest prices, distributions, splits | High fit, provider-dependent. Add cached enrichment and reviewed corporate-action processing (Phase 5). |
| Mobile/installable interface | Useful access layer. Prioritize responsive offline reports, then an optional local UI (Phases 4, 6). |
| Historical portfolio simulator | Useful after reliable price/event history. Reuse calculation contracts in an isolated simulation plugin (Phase 6). |
| Automatic B3 sync; IRPF/DARF assistance (PRO+ waitlist) | Conditional fit. Optional read-only regional connectors and versioned jurisdiction-specific tax plugins (Phases 5B, 6). |

Rikdom should adopt these user outcomes without adopting subscription tiers,
central custody of portfolio data, or a Brazil-specific core. Tax calculations,
live connections, and broad market coverage depend on maintained regional plugins;
they are not prerequisites for the free offline workflow.

## Existing foundation to reuse

- Importers for Portfolio Performance, Wealthfolio, IBKR, and other providers are
  already present; see [plugin catalog](plugins/README.md). B3's existing
  [monthly consolidated importer](plugins/b3-consolidado-mensal/README.md) imports
  holdings and `Movimentação` history. Source movement dates and institutions do
  not by themselves establish full history, account identity, or a trade-date basis.
- Holding provenance and reconciliation JSON/Markdown reports already ship through
  `reconcile`: [report implementation](src/rikdom/reconciliation/reports.py) and
  [CLI coverage](tests/test_cli_reconcile.py).
- [Performance calculations](src/rikdom/performance.py) already include Modified
  Dietz (an approximation of TWR), XIRR MWR, and account/strategic-bucket breakdowns.
  [Benchmarks](src/rikdom/benchmarks.py) support native-currency and composite series;
  foreign benchmark conversion into the reporting currency remains a gap.
- [Instrument performance](src/rikdom/instrument_performance.py) already uses dated
  activities and completeness checks. It is not yet a portfolio-wide realized /
  unrealized profit engine or an income calendar.
- [Policy contracts](src/rikdom/_resources/policy.schema.json) already describe
  allocations, rebalancing, guardrails, benchmarks, and tax rules. These declarations
  do not implement a rebalance planner or a jurisdiction-specific tax calculator.
- [Integrity-checked export bundles](docs/reference/export-format.md),
  [eight stable plugin hooks](docs/reference/plugin-hooks.md), deterministic data-hook
  fixtures, and a [compatibility policy](docs/explanation/plugin-compatibility.md)
  already exist. Extend these instead of treating them as new deliverables.

## Architectural context

Durable decisions applied across phases:

- **Storage**: local `JSON` (`portfolio.json`) + append-only `JSONL` snapshots.
- **Schema contract**: JSON Schema 2020-12 + explicit `schema_uri` and semantic `schema_version`.
- **Data model**: source `activities` ledger + derived `projections`; linked
  corrections preserve originals while ordinary imports may refresh matching
  source events (see [activity workflow](docs/how-to/enter-and-correct-activities.md)).
- **Plugin runtime**: in-process Python plugin engine using `pluggy`.
- **Plugin taxonomy**: lifecycle (`source/input`, `transform`, `enrichment`, `strategy/decision`, `execution`, `output`), explicit acquisition (`external/connector`), domain (`asset-type/catalog`), plus cross-cutting (`risk/compliance`, `state/storage`, `orchestration`, `observability`, `auth/security`, `notification`, `simulation/backtest`).
- **Plugin manifest**: `plugins/<name>/plugin.json` with `name`, `version`, `api_version`, `plugin_types`, `module`, `class_name`.
- **Import boundary**: `source/input` plugins return normalized statement JSON with provenance-ready fields.
- **Asset-type boundary**: `asset-type/catalog` plugins return typed asset definitions to compose `asset_type_catalog` before import/validation.
- **Output boundary**: `output` plugins can render portfolio reports; Quarto-based rendering is the prioritized pluginized path.
- **Storage boundary**: `state/storage` plugins can maintain optional query mirrors while canonical truth remains JSON files.
- **Idempotency**: imported objects carry `idempotency_key` and `import_run_id`.
- **Visualization**: static offline HTML generated from local files.
- **Calculation boundary**: reusable deterministic calculations belong in the
  foundation; providers, regional conventions, strategies, and presentation belong
  behind versioned plugin contracts. CLI and UI consume the same results.
- **Privacy boundary**: market-data lookups send only the identifiers/dates needed;
  portfolio contents and statements are not implicit API payloads. Credentials
  are scoped to explicitly enabled providers and kept out of stored artifacts.
- **Compatibility**: new permissions, provider series, or execution modes require
  explicit versioned contracts; they are not fields/hooks supported by v1 today.

---

## Adoption-first Priority Stack

1. **P0**: Harden import history, manual entry, and reconciliation; expose existing trust reports in user workflows.
2. **P0/P1**: Complete income views, usable offline reports, and beginner onboarding.
3. **P1**: Make returns, benchmarks, contributions, and profit decomposition comparable and auditable (Phase 4B).
4. **P1**: Deliver price/FX/event provider contracts and regional packs; harden plugin trust before unattended connections.
5. **P1**: Add custom views, policy-driven rebalance simulation, and local scheduled refresh.
6. **P1/P2**: Expand the SDK and remaining plugin hooks as concrete workflows require them.
7. **P2**: Historical simulations, jurisdiction-specific tax assistance, optional local UI, replayable exports, then optional AI.

Sequencing override:

- Complete trust/import/income foundations before expanding AI or advanced strategy plugins.
- Phase 4B historical calculations require the relevant Phase 5 data contracts;
  Phase 5A scheduling requires Phase 5B safeguards for any connected plugin.
- Do not wait for every taxonomy hook to ship a useful workflow. Add hooks with
  a reference implementation and contract tests, starting with enrichment and decisions.

---

## Phase 3 remainder (P0): Importer Coverage + Import Reliability Hardening

**User stories**: safe recurring imports from common portfolio tools into local files.

### What to build

- Ship remaining first-party importers targeting migration from widely used tools:
  - `portfolio_performance_csv`
  - `wealthfolio_export_json`
  - `wealthfolio_activity_csv` fallback
- Expand importer edge-case fixtures where coverage is still thin:
  - IBKR cancellations and corporate actions.
  - Portfolio Performance locale/date/number parsing.
  - Wealthfolio enum mapping and fallback behavior.
- Add B3 transaction-history file coverage alongside monthly holdings; report
  missing history instead of inferring purchases from current balances.
- Provide a local manual-entry/correction path for unsupported institutions and
  assets, using the same validation, provenance, and append-only ledger semantics.
- Extend locale, currency, identifier, and corporate-action fixtures as regional
  importers are added. Corrections and reimports must not duplicate events.

### Acceptance criteria

- [x] Ship first-party `portfolio_performance_csv` importer with locale/date/number parsing tests.
- [x] Ship first-party `wealthfolio_export_json` importer with enum mapping and fallback tests.
- [x] Ship `wealthfolio_activity_csv` fallback importer path with fixtures.
- [x] Add IBKR cancellation/corporate-action edge-case tests.
- [x] Import a B3 `Movimentação` history file twice without duplicating recognized activities; report unsupported movements and partial coverage.
- [x] Reconcile B3 positions with verified account/opening coverage and compatible execution/settlement-date evidence (reviewed complete inception history with zero opening; raw B3 remains partial).
- [x] Enter and correct a manual activity with preview/validation and an auditable correction trail.
- [x] Surface explicit history coverage and unsupported events for every first-party importer.

---

## Phase 3A remainder (P0): Calculation Trust UX + Reconciliation Reports

**User stories**: "numbers must be correct", reproducible valuation, explainability for portfolio totals and changes.

### What to build

- Integrate the existing holding-trust and reconciliation reports into the first
  import and report workflows, including activity/holding and cross-currency findings.
- Finish user-facing documentation and diagnostics for reproducing a total and
  understanding excluded holdings, missing history, and stale valuations.

### Acceptance criteria

- [x] Make each computed holding value traceable to source amount + FX + timestamp in an exported report.
- [x] Ensure reconciliation reports flag amount/quantity inconsistencies with actionable diagnostics.
- [x] Provide stable issue codes for reconciliation findings.
- [x] Document how to reproduce a portfolio total from raw holdings, activities, and FX history.

---

## Phase 4 remainder (P0/P1): Visualization Hardening

**User stories**: allocation overview and progress over time remain trustworthy and usable as reports grow.

### What to build

- Verify and harden desktop/mobile usability of generated reports.
- Keep Quarto report output and built-in dashboard behavior aligned while compatibility aliases remain.
- Add report-level diagnostics when trust/reconciliation issues affect displayed totals.
- Expose allocation, net contributions versus portfolio growth, performance, and
  income through consistent report filters as Phases 4A/4B deliver their results.
- Bundle report assets locally; an offline report must not depend on CDN scripts,
  remote fonts, trackers, or a hosted login. Treat generated financial reports as
  private files and provide a redacted sharing/export option.

### Acceptance criteria

- [x] Add mobile/desktop report usability checks or documented manual QA criteria ([browser QA guide](docs/how-to/report-browser-qa.md); generated full/fallback bundles checked in Chromium at 1440, 390, and 320 px).
- [x] Surface reconciliation/data-quality warnings in generated reports.
- [x] Keep deprecated visualization aliases covered until removal policy is decided (`viz`, `visualize`, and `render-report` exercise real output, warnings, legacy/custom paths, and local artifact links).
- [x] Open generated reports with networking disabled and retain existing charts, navigation, and explanations (Quarto 1.9.37 verified after bundle relocation; fallback remains a summary without charts).
- [x] Add consistent report filters for allocation, contributions/growth, performance, and income as Phases 4A/4B deliver their results; verify those controls offline (account, asset-type, and currency scopes plus recorded-date controls; current valuation remains current, and missing scoped history/return measures remain explicitly unavailable pending Phase 4B).
- [x] Verify keyboard navigation, readable mobile layouts, and localized labels/date/number formatting; begin with English and Portuguese (full/fallback Chromium checks at 1440, 390, and 320 px, EN/PT selectors and locale formatting; provider diagnostics retain labeled original source text).

---

## Phase 4A remainder (P0/P1): Dividend/Income + Onboarding Hardening

**User stories**: dividend automation, easy self-hosted start.

### What to build

- Dividend/income automation:
  - normalize dividend, interest, and cashflow activity variants from all first-party importers;
  - monthly/yearly income summaries;
  - report slices for income by portfolio, asset type, instrument, currency, and tax bucket where available.
  - separate received payments, announced entitlements, and scenario estimates;
  - preserve ex/record/payment dates, withholding, gross/net amounts, currency,
    source, and entitlement assumptions when available;
  - calculate yield on cost with a declared cost-basis method and period; missing
    basis must produce an unavailable result rather than a misleading yield.
- Beginner onboarding:
  - guided import checklist for first successful migration;
  - stronger docs/tests around the happy path from bootstrap to first report.

### Acceptance criteria

- [x] Roll up dividend and interest events into monthly/yearly native-currency income views.
- [x] Expose income views through the `income` CLI and JSON/Markdown report artifacts.
- [x] Ensure all first-party importers map dividend/interest/cashflow events consistently ([source coverage matrix](plugins/README.md#posted-income-coverage-by-source); signed corrections, separate tax/refunds, gross/net/unknown basis, and zero versus missing evidence are tested through import/replay; unsupported and holdings-only sources remain explicit).
- [x] Enable new users to run bootstrap + first import using a documented happy path in under 15 minutes (10–15 minute walkthrough estimate after installation, not a measured usability result).
- [x] Display paid and announced income separately; forecasts never enter actual balances or realized returns (local [income plan v1](docs/reference/income-plan.md), separate actual/announced/scenario sections in CLI and offline reports; source and ex/record/payment-date evidence remain explicit).
- [x] Match imported payments to announced events without double-counting reinvested distributions, corrections, or repeated provider refreshes (reviewed explicit links resolve effective corrections and deduplicate payments/revisions; no inferred entitlement or automatic amount/date match).
- [x] Explain yield-on-cost inputs and flag unavailable cost basis; distinguish gross income from net receipts (`declared_constant_cost` requires positive native-currency basis, source, coverage, method, and full explicit period; changing-cost or incomplete inputs remain unavailable, with no FX substitution or automatic annualization).
- [x] Complete onboarding with sample data and no account, paid API key, or AI service (local import/replay, trust, income, snapshot, and fallback HTML verified with network connections denied).


### Small extension: collective dividend-receipt validation

Recorded **2026-10-28**. **Status:** hypothesis to test, not a committed hosted
product or validated business. **User question:** "Have other customers of my
broker received this dividend, and is my result unusual?"

- Reuse local imports and announced-versus-received reconciliation. Start with
  one supported broker entity, one account category, and a few commonly held
  distributing instruments; this experiment must not block core Phase 4A delivery.
- First establish date semantics: distinguish the issuer's announced payment
  date, the broker's accounting date, first observation in successive imports,
  and actual cash availability only when explicitly supported by the source.
  Import frequency bounds first observation; backdated entries are not proof of
  availability. The current IBKR `effective_at` alone is insufficient.
- Provide a useful local payment check before inviting an optional contribution.
  Compare that result with aggregate peer observations to test whether collective
  data resolves uncertainty that announcements and a personal statement cannot.
  Missing records must surface statement coverage and entitlement uncertainty,
  not automatically accuse a broker of a missing or delayed payment.
- Keep statements and portfolios local. Preview explicitly opted-in contributions
  limited to public distribution identity, broker entity, coarse timing, coverage,
  and importer version; exclude balances, quantities, account/transaction IDs,
  source references, and free text. Download aggregates for local matching.
  Suppress sparse cohorts and public contributor histories; assess re-identification
  and duplicate/fabricated contribution risks before claiming anonymity or trusted
  peer counts. Connected operation follows Phase 5B safeguards.
- Test organic discovery through shareable aggregate event pages that invite a
  local check and optional contribution. Do not require sharing to use Rikdom's
  free offline workflows. Fees, FX comparisons, subscriptions, and a general data
  hub remain outside this initial experiment.

**Validation gates (proposed thresholds, not observed results):**

- [ ] Timebox a date/coverage feasibility check to two days; stop the timing hypothesis if available sources cannot support it reliably.
- [ ] Run a four-to-six-week self-service experiment after feasibility passes: 30 independent users complete the workflow without personal onboarding, 15 contribute voluntarily, and 10 contribute again in another payment cycle.
- [ ] Record at least five concrete uncertainties resolved by the collective result beyond the local-only report, and five additional activated users arriving through shared aggregate pages.
- [ ] Record cohort coverage, repeat usage, contribution quality, and privacy limitations; synthetic fixtures validate mechanics only, never demand or network effects.
- [ ] At the experiment's end, retain findings and remove the disposable collection setup and contributed records under a disclosed retention policy. Continue only if the gates pass; otherwise keep useful local reconciliation and stop the hub experiment. Passing these gates does not establish willingness to pay or commercial viability.

---

## Phase 4B (P1): Comparable Performance + Profit Attribution

**User stories**: understand how much growth came from contributions, investments,
income, and currency movements; compare a strategy with an appropriate benchmark.

### What to build

- Retain existing Dietz/XIRR results with clear method and annualization labels;
  add linked subperiod TWR when valuations around external cashflows are available.
- Add dated price/FX inputs and cashflow conversion at the relevant historical
  dates. Never silently substitute today's FX or a stale quote for missing history.
- Reconcile contributions/withdrawals, realized and unrealized gains, income, fees,
  taxes, and FX effects. Cost-basis and lot accounting conventions must be explicit;
  reported gains and calculated gains need distinct provenance.
- Compare benchmark and portfolio series over the same window, currency, and
  price/total-return convention. Regional benchmark packs can supply CDI, IBOV,
  S&P 500, or other indices through replaceable data providers.
- Render monthly/yearly tables, charts, and optional heatmaps from the same result
  contracts used by CLI, avoiding independent frontend financial calculations.

### Acceptance criteria

- [ ] Demonstrate linked TWR and XIRR with hand-checkable contributions/withdrawals, internal transfers, and corporate actions; identify Dietz fallback explicitly.
  - Partial delivery (2026-10-29): [explicit flow-boundary valuations](docs/reference/performance-output.md) support portfolio linked TWR, with Dietz compatibility and method/fallback/annualization disclosure. Internal-transfer identity and dated foreign-currency conversion remain open; ordinary snapshots do not establish pre/post-flow evidence.
- [ ] Reconcile a multi-currency example using dated FX and disclose missing/approximate history in every affected metric.
  - Partial delivery (2026-10-29): [local historical FX](docs/reference/historical-fx.md) converts dated external cashflows in portfolio/account/bucket performance, retains lookup evidence, and makes affected returns unavailable on missing/stale inputs. A [synthetic offline example](docs/how-to/compute-performance.md#replay-dated-fx-for-cashflows-and-benchmarks) links explicit cashflow-boundary valuations. Reconstructing snapshot valuation FX and full profit/FX attribution remain open.
- [ ] Reconcile opening value + net contributions + investment result to closing value, with documented rounding and no double-counted income.
- [ ] Explain realized/unrealized gains with lot/cost-basis evidence; incomplete history cannot produce an apparently complete profit total.
- [ ] Compare portfolio and foreign/composite benchmarks in a common currency and period, with return convention and data provenance visible.
  - Partial delivery (2026-10-29): [historical benchmark conversion](docs/reference/benchmark-fx.md) converts local benchmark bookends and every active composite component before blending; comparable excess requires matching dates, source evidence, and total-return convention. Missing components do not silently renormalize a complete-looking composite. Snapshot return conventions and report integration remain caller-dependent/open.
- [ ] Reproduce the CLI figures in an offline report, including method, annualization, fees/taxes treatment, and data-quality warnings.

---

## Phase 5 remainder (P1): Full Plugin API + SDK Hardening

**User stories**: community-contributed adapters across the full pipeline and shared asset-type packs.

### What to build

Expand from the shipped import/catalog/output/storage foundation to full lifecycle/cross-cutting coverage:

- Complete hook coverage for lifecycle plugin types not yet implemented:
  - `transform`
  - `enrichment`
  - `strategy/decision`
  - `execution`
- Add or stabilize cross-cutting hooks and contracts:
  - `risk/compliance`
  - `auth/security`
  - `notification`
  - `simulation/backtest`
  - orchestration policies for multi-step plugin pipelines.
- Harden SDK scaffolding and examples for each supported plugin type.
- Keep compatibility checks and fixture-based contract tests broad enough for community plugin packs.
- Prioritize `enrichment` contracts for prices, FX, distributions, and corporate
  actions: source, instrument identity, effective/retrieved timestamps, currency,
  adjustment convention, coverage, and data-license metadata. Cache inputs locally
  for replay; corrections must remain traceable.
- Add regional catalog/provider packs with namespaced identifiers (exchange +
  ticker, ISIN where available, provider mappings), market calendars, and asset
  conventions. Brazilian fixed-income indexers/maturities belong in a regional
  pack; valuation must distinguish contractual accrual from market quotes.
- Start with BR/US reference packs using existing imports, then demonstrate a
  third market and reporting currency without a core country-specific code path.
- Publish a plugin coverage matrix: supported markets/assets/events, offline
  inputs, dependencies, license, API costs/quotas, and maintenance status.

### Acceptance criteria

- [ ] Define and document hooks for `transform`, `enrichment`, `strategy/decision`, and `execution` plugins.
- [ ] Define and document `risk/compliance`, `auth/security`, `notification`, and `simulation/backtest` plugin contracts.
- [ ] Add SDK templates/examples beyond source-input plugins.
- [ ] Check plugin fixtures against schema and hook contracts in CI for every supported plugin type.
- [x] Publish compatibility policy for breaking hook or manifest changes.
- [ ] Replay cached provider inputs offline with the same financial results; report stale/missing series explicitly.
  - Partial delivery (2026-10-29): the [local market-series contract](docs/reference/market-series.md) validates price/FX files and replays observations with revision provenance, retrieval cutoff, coverage, and explicit missing/stale statuses. Wiring those inputs into historical financial calculations and provider hooks remains open.
- [ ] Preview and apply a split/distribution correction idempotently without adjusting already-adjusted prices or duplicating ledger events.
- [ ] Run a third-market reference pack against shared contracts without modifying the core for that country.
- [ ] Support file/manual series as a free fallback for each reference provider workflow; publish coverage and licensing limits.

---

## Phase 5A remainder (P1): Custom Groups + Rebalance Planning + Local Automation

**User stories**: no-surprises operation, low-friction recurring updates, safe experimentation.

### What to build

- Data quality guardrails:
  - drift detection between activities and holdings;
  - policy-driven warnings vs blocking failures;
  - dashboard/report surfacing for guardrail findings.
- Scheduled refresh:
  - recurring snapshot/import orchestration for end-of-day updates;
  - diagnostics for scheduled run failures.
- Paper/experimental portfolio policy hardening:
  - explicit inclusion/exclusion rules in consolidated views;
  - labels and safeguards to prevent accidental mixing with real totals.
- Custom groups and policy views:
  - reuse strategic allocation buckets; add saved user classifications and filters
    by account, instrument, asset class, currency, and region;
  - distinguish overlapping analytical tags from allocation groups so a holding
    is not counted twice in totals or target weights.
- Rebalance planning through `strategy/decision` and `risk/compliance`:
  - consume the existing policy's targets, bands, constraints, and available cash;
  - support contribution-only allocation first, then optional simulated buy/sell
    plans with lot sizes, fractional units, fees, and declared tax assumptions;
  - show current/target/proposed weights, quantities, residual cash, assumptions,
    and blocked actions. Export a plan without changing actual holdings.
- Use an OS scheduler/local orchestration for recurring imports and snapshots;
  no hosted scheduler is required. Price refresh and account synchronization are
  different operations, each with explicit permissions and diagnostics.

### Acceptance criteria

- [ ] Run drift guardrail checks consistently and surface machine-readable issue codes.
- [ ] Allow scheduled runs to append snapshots and emit import/validation diagnostics.
- [ ] Exclude paper portfolios from real portfolio totals by default with explicit opt-in for rollups.
- [ ] Surface scheduled-run and guardrail status in reports.
- [ ] Save custom groups and round-trip them through canonical data/export without changing instrument identity or double-counting totals.
- [ ] Produce a deterministic contribution-only plan and a buy/sell simulation from a versioned policy; show constraints and residual cash.
- [ ] Leave the actual ledger unchanged after planning and reject invalid targets or insufficient valuation data with actionable diagnostics.
- [ ] Recover from a failed/repeated scheduled run without duplicated activities or partial canonical writes; retain last-success and failure status locally.

---

## Phase 5B (P1 gate for connected automation): Plugin Trust + Private Operation

**User stories**: know what a plugin can access, keep credentials and portfolio
data under local control, and restore data safely after a failure.

The [current runtime](docs/explanation/plugin-architecture.md#operational-safety)
loads trusted Python in-process with no sandbox. A manifest permission or an
`auth/security` hook cannot restrain arbitrary code in that process. These are
planned safeguards, not existing security guarantees.

### What to build

- Document the trust boundary at plugin installation/loading; record pinned
  versions, dependency provenance, requested access, and a reviewable inventory.
- Evolve manifest/API contracts for filesystem, network destinations, secrets,
  and execution permissions. Provide a constrained execution mode with enforcement
  outside plugin code before accepting untrusted plugins or claiming isolation.
  Retain trusted Pluggy mode with an explicit warning about its actual privileges.
- Make connected providers optional, read-only, scoped, and revocable. Prefer
  minimum identifier/date queries; keep secrets in OS-backed secret storage and
  redact logs/reports. No portfolio upload, telemetry, or cloud AI by default.
- Document OS/disk protection for canonical files and add an encrypted backup
  option with a tested recovery procedure. Checksums establish integrity, not
  confidentiality. Keep the existing portable unencrypted export option explicit.

### Acceptance criteria

- [ ] Show plugin identity/version and requested access before enabling a connection; revocation prevents subsequent credential use.
- [ ] In constrained mode, demonstrate denied filesystem/network access with adversarial fixtures; refuse to label an unsupported platform as isolated.
- [ ] Run the reference import → reconcile → performance → report → export flow with networking disabled after installation, using only local inputs.
- [ ] Verify that logs/artifacts omit credentials and unnecessary account data; remote requests send only the selected provider's authorized authentication and minimum required inputs.
- [ ] Restore an encrypted backup into a fresh workspace and reproduce totals; reject corrupted bundles and wrong keys without partial writes.

---

## Phase 6 (P2): Historical Simulation + Regional Tax + Optional Interfaces

**User stories**: richer analysis and portability ecosystem.

### What to build

- Extend the already-shipped interchange bundle with versioned replay metadata,
  input-series hashes, plugin/policy versions, and license-aware inclusion of cached
  prices/FX/events. Preserve v1 import compatibility.
- Historical simulation plugin: initial capital, start/end dates, asset weights,
  recurring contributions, rebalancing, and reinvestment assumptions. Reuse the
  performance engine; isolate simulated state from real portfolios. Report fees,
  slippage, FX, corporate-action treatment, missing history, and survivorship /
  look-ahead limitations. Fixed-income product simulations need their own dated
  cashflows and terms; an index comparison is not a product simulation.
- Regional tax plugins: use existing activities, tax lots, and policy contracts;
  add jurisdiction, tax year/effective dates, supported account/instrument types,
  rule sources, and reproducible calculation traces. A BR reference pack may
  prepare IRPF/DARF workpapers; the existing `irpf-xml` importer is not a tax engine.
  Keep filing/payment outside the initial scope and mark unsupported cases.
- Optional local interface: explore a thin browser/desktop frontend consuming
  the same contracts, with guided imports, groups, reports, and simulation previews.
  Keep CLI/static reports fully usable; bind any local service to loopback by
  default and protect file access and state-changing requests. Mobile access must
  not require exposing the portfolio service to the public internet.
- Optional AI decision/explanation plugins only after the deterministic workflows
  above. Provide a local-model path; external inference requires explicit opt-in
  and scoped data sharing. AI must cite calculation artifacts and never become the
  financial source of truth or a requirement for using the product.

### Acceptance criteria

- [x] Deliver a self-describing, integrity-checked export package.
- [ ] Reproduce a report/simulation from an extended bundle offline and retain compatibility with existing bundles.
- [ ] Run a deterministic historical simulation with contributions and corporate actions; expose coverage/bias limits and leave real totals unchanged.
- [ ] Validate a first jurisdiction/year tax pack against documented fixtures, including disposals, withholding, and supported loss carryforward cases; reject unsupported rules explicitly.
- [ ] Demonstrate that a second jurisdiction uses the same neutral contracts without embedding its rules in the core.
- [ ] Validate an optional local UI against the same CLI results and Phase 5B privacy requirements before treating it as a supported interface.
- [ ] Define AI plugin interfaces with guardrails/audit requirements before general enablement.

---

## Execution planning

For each new phase, create focused implementation issues with prerequisites,
reference fixtures, core/plugin ownership, and the acceptance criteria above.
No phase requires feature parity with an unverified paid service before delivering
a useful free local workflow.
