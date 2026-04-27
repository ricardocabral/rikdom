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

Numbers may use either `.` or `,` as decimal separator; both are normalized via
`rikdom.import_normalization.parse_decimal`. Dates accept ISO 8601 and the German
`DD.MM.YYYY` form (with optional `Time`/`Uhrzeit` column appended).

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin portfolio_performance_csv \
  --plugins-dir plugins \
  --input tests/fixtures/portfolio_performance_export_de.csv \
  --portfolio tests/fixtures/portfolio.json
```
