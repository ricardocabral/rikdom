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

Snapshot chronology follows valid timestamp instants, and all renderers consume
that same Python order. Snapshot date filters and labels use the calendar day
written at the source offset, independent of browser timezone. Detailed times
retain the written source clock and offset. Missing, malformed, offsetless or
impossible dates remain in `sections.unavailable_snapshots` with a quality warning;
they do not enter chronological charts or change summaries. No canonical history
is rewritten. Custom asset identifiers remain opaque; Portuguese translates
only exact known enum labels.

## Offline investment performance

`sections.performance` uses the same `performance_result_to_dict` contract as
`rikdom performance`. Both Quarto pages and fallback pages display the selected
TWR method, legacy Dietz approximation, XIRR, period versus annualized basis,
actual snapshot window, currency, warnings and growth bridge. The bridge is a
residual reconciliation, not a realized/unrealized or FX attribution engine.
Income is embedded in snapshot values and is never added again. Fees and taxes
are embedded in valuations, not separately calculated. Missing or invalid inputs
remain unavailable; the report never fetches financial data.

Optional evidence is explicitly selected under the existing report extension:

```json
{
  "extensions": {
    "rikdom_report": {
      "locale": "en",
      "performance": {
        "flow_valuations_path": "flow-valuations.json",
        "historical_fx_path": "historical-fx.json",
        "policy_path": "policy.json",
        "benchmarks_dir": "benchmarks",
        "since": "2026-01-01",
        "until": "2026-12-31"
      }
    }
  }
}
```

All performance options are optional. Paths are local files/directories and are
relative to the portfolio file, or absolute. Historical FX configuration resolves
its market-series file relative to that configuration. Evidence uses the same
contracts as CLI `--flow-valuations`, `--historical-fx`, `--policy` and
`--benchmarks-dir`; use the same files and window to reproduce the CLI result.
Without historical FX, optional `fx_history_path` selects the CLI-compatible local
undated FX history (default `fx_rates.jsonl` beside the portfolio). The report's
current-valuation snapshot FX lock is never substituted for historical cashflows.
Policy benchmarks default to the `benchmarks` directory beside the portfolio.
Legacy undated FX remains approximate as disclosed by the core. Invalid selected
files/configuration make performance unavailable without discarding other report
sections. Invalid snapshot timestamps also make performance unavailable, rather
than silently removing those records from the calculation.

The visible window is the actual selected snapshot bookends, which can differ
from requested `since`/`until` bounds. Interactive date filters make performance
unavailable until reset; they do not recalculate or relabel the original window.
Account, currency and asset-type scopes also keep performance unavailable because
the report has no attributable scoped return contract. Current valuation and
recorded-income filters continue to work independently.

Benchmark comparisons retain the core currency, return convention, comparability,
actual dates and excess-return availability. The expandable provenance section
contains the original calculation contract, flow-valuation sources, FX lookup
and benchmark evidence, warnings and rounding convention. Local configuration
paths are represented by filenames, not copied as absolute paths. Source text is
escaped and preserved; interface labels and numeric formatting support English
and Portuguese. JavaScript formats supplied financial figures and selects
unavailable states; it performs no financial calculations.
