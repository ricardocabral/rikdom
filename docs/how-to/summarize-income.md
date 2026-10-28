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
was owed or paid. Tax filing remains outside this report.

## Compare announcements with actual payments

Pass a local [versioned income plan](../reference/income-plan.md) to keep announced
entitlements and scenario estimates separate from received money:

```bash
uv run rikdom income \
  --portfolio tests/fixtures/income_planning_portfolio.json \
  --income-plan tests/fixtures/income_plan.json \
  --out-dir out/income-planning
```

These tracked synthetic inputs need no account, API key, or network connection.
The example has USD 50 of received gross income, a USD 50 announcement, and a
separate USD 999 scenario estimate. Actual received income stays USD 50. The
declared USD 1,000 constant cost basis produces a 5% yield for its explicit
2026 period; this is not an annualized forecast or a tax-lot calculation.

Inspect the JSON `planning` object or the Markdown sections for announcements,
estimates, payment reconciliation, and yield on cost. Each announcement includes
a source, revision, scope, and payment date. Ex and record dates can be retained
when supplied. A per-unit announcement needs explicit entitlement evidence;
today's holdings do not establish historical eligibility.

Only reviewed `payment_links` match an announcement to an imported activity.
Do not create links merely because dates or amounts look alike. Repeated links
and refreshes do not add income; corrections resolve to the effective activity.
A reinvestment purchase is not another dividend payment. Unlinked or unavailable
results describe uncertain evidence, not proof of a missing or delayed payment.

Use the plan's `cost_bases` only when the declared method, period, source,
currency, and statement coverage are supported. The initial method is
`declared_constant_cost`, with no automatic FX conversion or annualization.
Missing basis, unknown income, incomplete coverage, or capital changes that
invalidate the constant denominator make yield unavailable with an explanation.
The report distinguishes gross income from net receipts instead of treating
missing withholding as zero.

You can also place the same plan object under
`portfolio.extensions.rikdom_income_plan` for report generation. An explicit
`--income-plan` overrides the embedded plan. Invalid supplied plans stop the
income command before artifact writes. Neither path creates activities, changes
holdings, or changes realized returns. Keep canonical inputs and plan files
separate from artifact filenames.

See the [income CLI reference](../reference/cli.md#income) for flags and the
amount-basis contract.
