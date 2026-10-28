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

## Received income and replay

Dividend, interest and generic `Income`/`Income Adjustment` rows preserve signed
amounts. Their CSV `amount` does not declare gross versus net, so these events
carry `metadata.rikdom_income = {"version": 1, "amount_basis": "unknown"}`.
Reported income fees keep their signs and explicit zero values; absent fees and
withholding are not filled with zero. Fees use the transaction currency. An
explicit invalid transaction currency is rejected; an omitted currency retains
the existing account-currency/USD convention.

Explicit withholding, `Tax`, `Taxes`, `Tax Withheld` and `Tax Refund` actions map
to separate signed `tax_withheld` events, before dividend/interest matching.
Instrument words such as `TAXF` and `Tax-Exempt Bond` are not tax actions. No
withholding rows are linked to dividends automatically. Attached tax amounts,
separate fee currencies and explicit gross/net amounts require reviewed canonical
JSON through `normalized-statement-json`.

Legacy activity IDs and idempotency keys remain stable, including previously
positive-normalized negative income. Conflicting rows sharing that legacy
identity fail instead of losing a correction. Duplicate confirmed references
with different source fingerprints retain the existing digest-ID fallback.
Source identity metadata allows import preflight to block economic rewrites of
legacy stored rows for review; use an auditable canonical correction for such a
change. Repeated imports of unchanged output do not add or update events.
