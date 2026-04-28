# Fidelity source/input plugin

Imports Fidelity-style CSV statement exports into Rikdom canonical statement JSON.

## Supported input

Version 1 supports a single CSV file with normalized statement rows. The fixture format is intentionally machine-readable and can be produced from Fidelity exports or statement ETL scripts.

Required columns vary by `record_type`:

- `account`: `record_type`, `account_number`, optional `account_name`, `account_type`, `statement_date`, `currency`
- `position`: `record_type`, `account_number`, `symbol`, `description`, `quantity`, `market_value`; optional `security_type`, `cusip`, `currency`
- `cash`: `record_type`, `account_number`, `cash_balance`; optional `currency`
- `transaction`: `record_type`, `account_number`, `date`, `action`, `amount`; optional `symbol`, `description`, `quantity`, `fees`, `reference_id`, `currency`

The importer normalizes these Fidelity activity patterns:

- buy / purchase / reinvestment -> `buy`
- sell / redemption -> `sell`
- dividend -> `dividend`
- interest -> `interest`
- fee / commission / advisor -> `fee`
- deposit / contribution / transfer in -> `transfer_in`
- withdraw / distribution / transfer out -> `transfer_out`

## Usage

```bash
rikdom import-statement \
  --plugin fidelity \
  --plugins-dir plugins \
  --input plugins/fidelity/fixtures/taxable-brokerage/input.csv \
  --portfolio tests/fixtures/portfolio.json
```

For a dry-run merge preview, add `--dry-run` and omit `--write`.

## Fixtures

- `fixtures/taxable-brokerage/` models an individual taxable brokerage account with stocks, ETFs, cash, buys, sells, dividends, interest, and fees.
- `fixtures/retirement-ira/` models a traditional IRA pattern with mutual funds, core money-market holdings, contribution, reinvestment, and distribution activity.
- `fixtures/invalid-amount/` verifies failure handling for malformed transaction amounts.

## Known gaps

- PDF parsing is not supported.
- Advanced options activity is not mapped beyond `other` in v1.
- This plugin expects a single statement file and does not reconcile multiple Fidelity files across statement periods.
- Fidelity web exports vary by screen/account type; unsupported CSV headers should be converted to the normalized rows documented above before import.
