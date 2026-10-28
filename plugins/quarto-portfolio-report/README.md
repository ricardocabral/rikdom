# quarto-portfolio-report

Pluggy `output` plugin that renders a portfolio report with Quarto.

## Prerequisites

Install Quarto CLI and ensure it is available in `PATH`:

```bash
brew install --cask quarto
quarto --version
```

If Quarto is missing, the plugin still runs but generates a fallback HTML artifact.

## Run

Quick target from repo root:

```bash
make viz
```

Full command:

```bash
uv run rikdom viz \
  --portfolio data-sample/portfolio.json \
  --snapshots data-sample/snapshots.jsonl \
  --out out/reports/dashboard.html
```


## Current values and trust artifacts

The output plugin builds core aggregation results for the current holdings and
each available single-dimension scope.
Its total, base-currency holding amounts, allocations, and excluded holdings all
use that result. Historical snapshot totals remain a separate timeline; they do
not replace the current valuation.

The current valuation uses the latest supplied compatible snapshot FX lock,
then the existing per-holding metadata fallback. It never acquires rates or
contacts a provider. Available lock effective dates and sources appear in trust
context; unknown or older rate dates stay visible as warnings. Report generation
time is separate from the rate's effective date.

Both views and fallback HTML include a small data-quality section with coverage,
quantity comparison counts, exclusions, warnings, and local links to:

- `holding_trust.json` and `holding_trust.md`
- `reconciliation.json` and `reconciliation.md`

These artifacts use the same report builder and writer as `rikdom reconcile`.
Zero findings do not establish complete history. Coverage describes only the
explicitly declared source scopes and periods.

## Offline browser checks

Keep the complete output bundle together, including `report-data.js` and generated
`*_files/` assets. Both pages open directly from disk and link to each other.
Fallback output clearly reports its reason and retains valuation/trust links; it
does not include charts or the detailed holdings table.

See [report browser QA](../../docs/how-to/report-browser-qa.md) for desktop/mobile
checks and the opt-in Playwright regression.


## Local filters and languages

Both full and fallback output provide English/Portuguese selection, account,
asset-type or currency scopes, and inclusive recorded-date limits. The controls
work offline. The language is carried in the sibling-navigation link; it does
not require browser storage. English is the default. An optional canonical
extension selects the initial language:

```json
{"extensions": {"rikdom_report": {"locale": "pt"}}}
```

Use `en` or `pt`. This adds no `settings` schema fields or CLI flags.

A scope selects one asserted dimension at a time. Python precomputes current
valuation, allocations, holdings shares and historical change summaries. It
also supplies canonical received-income facts and optional income planning.
The browser selects rows and formats them; it does not calculate income,
matching, yields or investment returns. Existing payload keys are retained;
`report_views` adds scoped sections and `sections.presentation` adds calculated
presentation facts.

Date filters narrow recorded snapshots, contributions/withdrawals, received
income, and plan payment dates. They do not value today's holdings at a past
date. Historical monetary summaries are hidden with date filters. Scoped
historical charts are unavailable because the supplied snapshots do not assert
account/asset-type/currency attribution. A snapshot valuation change is never
presented as an investment return. No missing record is represented as zero.

Received amounts preserve native currencies and unknown withholding/fees.
Rows without the selected historical dimension are excluded; today's holdings
do not supply missing attribution. Contributions display source records without
inventing an FX-converted total or a contribution-versus-growth decomposition.

When `extensions.rikdom_income_plan` is supplied, separate tables show announced
income, scenario estimates, reviewed payment matching, and yield on declared
cost basis. Planning filters use each row's asserted scope and payment date.
Yield rows retain source, method and declared period, and become unavailable
when date limits omit part of that period. Gross/net basis and unknown reasons
stay visible; yields are not annualized. With no plan, the unavailable state is
explicit. Raw diagnostics and source assumptions retain their original text;
interface labels, numeric formatting and dates follow the selected language.
