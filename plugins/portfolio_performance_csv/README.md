# portfolio_performance_csv

Pluggy `source/input` plugin that imports activities from a Portfolio Performance CSV export.

## Expected Input

CSV exported from Portfolio Performance (`File → Export → CSV`). Both English and German
headers are accepted; delimiter is auto-detected (`;`, `,`, tab, or `|`).

Recognized columns (English / German):

- `Date` / `Datum`, `Time` / `Uhrzeit`
- `Type` / `Typ` — Buy/Kauf, Sell/Verkauf, Dividend/Dividende, Interest/Zinsen,
  Deposit/Einlage, Removal/Entnahme, Fees/Gebühren, Taxes/Steuern,
  Transfer (Inbound)/Umbuchung (Eingang), Delivery (Inbound)/Einlieferung, etc.
- `Value` / `Wert` (signed cash flow)
- `Transaction Currency` / `Buchungswährung`
- `Gross Amount` / `Bruttobetrag`, `Currency Gross Amount` / `Währung Bruttobetrag`
- `Fees` / `Gebühren`, `Taxes` / `Steuern` (with their currency columns)
- `Shares` / `Stück`
- `ISIN`, `WKN`, `Ticker Symbol` / `Ticker-Symbol`, `Security Name` / `Wertpapiername`
- `Note` / `Notiz`

## Locale

Numeric parsing uses an explicit source dialect: semicolon exports use comma
decimals and dot grouping; other delimiters use dot decimals and comma grouping.
Dates without a timezone use UTC. Dates accept ISO 8601 and the German
`DD.MM.YYYY` form (with optional `Time`/`Uhrzeit` column appended).

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin portfolio_performance_csv \
  --plugins-dir plugins \
  --input tests/fixtures/portfolio_performance_export_de.csv \
  --portfolio tests/fixtures/portfolio.json
```

## Received income semantics

For dividend/interest rows, `Value` stays in `Transaction Currency` and is marked
`metadata.rikdom_income = {"version": 1, "amount_basis": "net"}`. Taxes are preserved
in both `metadata.taxes` and canonical `withholding_tax`; fees and taxes retain
source signs, explicit zeros and native currencies. Missing tax stays missing.
Do not subtract charges again from this net amount.

If Value is absent, `Gross Amount` requires its own `Currency Gross Amount` and is
marked `gross`. Transaction Currency is never used to relabel a foreign gross
amount. Unlabelled fees/taxes use Transaction Currency. Cross-currency fields stay
separate; the importer does not apply Exchange Rate. Original monetary fields are
preserved in `metadata.source_money` for income rows. Invalid supplied monetary
values fail visibly. Existing supported row IDs remain unchanged.

These rules follow the official [CSV export description](https://help.portfolio-performance.info/en/reference/file/export/)
and [currency/import guide](https://help.portfolio-performance.info/en/how-to/import-gbx/).
They cover the supported English/German headers and do not claim every PP export
layout is equivalent. Previously imported unmarked rows need reimport or explicit
correction to acquire the new basis and withholding evidence.
