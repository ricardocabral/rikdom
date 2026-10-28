# Summarize received dividends and interest

Generate monthly and yearly income reports from your imported local activity
ledger. Import a statement first using the [statement guide](import-a-statement.md).
This calculation runs offline and requires no provider account or API key.

## Generate reports

```bash
uv run rikdom income --data-dir data --out-root out \
  --start 2026-01-01 --end 2026-12-31
```

The command prints JSON and writes JSON and Markdown reports under
`out/reports`. Use `--format json` or `--format markdown` to choose an artifact
format, or `--out-dir out/income` to choose a destination. In a registered
workspace, add `--portfolio-name <name>` to select a portfolio and isolate its
report directory. The command leaves canonical portfolio files and import logs
unchanged.

Open the Markdown artifact to inspect monthly and yearly totals. Each currency
has its own row; compare EUR with EUR and BRL with BRL. Income is not converted
using today's exchange rate. Dates use the calendar day in each event's
`effective_at` timestamp, including its stated offset; the filter endpoints are
inclusive. This date is the imported accounting/effective date, not proof that
cash became available that day.

## Check incomplete amounts

Inspect the report diagnostics before treating a subtotal as complete. A missing
withholding amount does not establish zero tax: an income event may have known
gross income and unavailable net receipts. An explicit zero withholding is a
known amount. Cross-currency fees or taxes remain separate evidence and are not
subtracted without a conversion contract.

The event rows retain asserted account, holding, instrument and asset-type
references so you can trace each payment to the ledger. Correct a mistaken
entry with the [auditable correction workflow](enter-and-correct-activities.md),
then regenerate the income report. Only the current effective event contributes;
the original remains stored for inspection.

Only posted dividend and interest events enter these received-income totals.
Pending events are not assumed to be announced distributions. Cancelled events,
transfers, contributions, generic income and reinvestment purchase legs are
excluded. The associated posted dividend remains income when it is reinvested.
For files imported with an older importer, preview a reimport of the original
source and inspect the resulting basis and withholding evidence before relying
on gross/net comparisons. Alternatively, correct the activity explicitly.
Unmarked historical events follow the canonical gross convention; the report
cannot infer their original source columns. Importer-specific semantics are
documented for [Portfolio Performance](../../plugins/portfolio_performance_csv/README.md#received-income-semantics),
[Wealthfolio CSV](../../plugins/wealthfolio_activity_csv/README.md#received-income-semantics),
[Wealthfolio JSON](../../plugins/wealthfolio_export_json/README.md#received-income-semantics),
[IBKR](../../plugins/ibkr_flex_xml/README.md#received-income-semantics), and
[B3](../../plugins/b3-consolidado-mensal/README.md).

Coverage depends on your imports: an empty report is not evidence that no income
was owed or paid. Announced-event matching, forecasts, yield on cost and tax
filing are separate roadmap work.

See the [income CLI reference](../reference/cli.md#income) for flags and the
amount-basis contract.
