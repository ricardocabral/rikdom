# ghostfolio_export_json

Pluggy `source/input` plugin that imports holdings and activities from a Ghostfolio JSON export.

## Expected Input

JSON exported from Ghostfolio API/client containing one or both:

- activity-like rows (`activities`, `transactions`, or `orders`)
- holding-like rows (`holdings`, `positions`, or `assets`)

The importer accepts top-level arrays/objects and common nested envelopes (`data`, `result`, `export`).

## Income evidence

Dividend, interest, and generic income preserve signed amounts. `TAX`,
`TAX_REFUND`, `WITHHOLDING_TAX`, and `TAX_WITHHELD` map to separate signed
`tax_withheld` events. A separate tax event does not establish an income row's
withholding.

The first available amount alias is selected in this order: `amount`, `value`,
`netAmount`, `grossAmount`. Income declares `metadata.rikdom_income` version 1
with `amount_basis: "net"` for `netAmount`, `"gross"` for `grossAmount`, and
`"unknown"` for ambiguous `amount`/`value`. No gross/net meaning is assumed from
a generic Ghostfolio-compatible envelope. Secondary aliases are also validated;
invalid evidence is never silently replaced by another amount.

Attached fees (`fee`, `fees`, `feeAmount`) and withholding (`withholdingTax`,
`withholding_tax`, `withholdingTaxAmount`, `tax`, `taxes`, `taxAmount`) retain
signed values and explicit zero. Blank or missing amounts remain absent.
Monetary fields accept a number or an `{amount, currency}` object. An object's
currency or an explicit alias currency (for example `feeCurrency`,
`withholdingTaxCurrency`, or `taxCurrency`) takes precedence over the activity
currency. Scalar amounts without a dedicated currency use the declared activity
currency (`currency`, `currencyCode`, `valueCurrency`, `accountCurrency`);
missing or invalid currency evidence is rejected. Cross-currency charges are
preserved without conversion. Non-finite and malformed monetary evidence is rejected,
including unused secondary aliases.

Anonymous IDs still hash the original source row; income metadata does not change
that identity. Preview reimports of previously imported income: ordinary source
rows may update, while corrected or superseded rows retain the existing ledger
protections. Use an [auditable correction](../../docs/how-to/enter-and-correct-activities.md)
or a [reviewed normalized statement](../../docs/how-to/import-a-statement.md) when
repairing stored evidence.

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin ghostfolio_export_json \
  --plugins-dir plugins \
  --input tests/fixtures/ghostfolio_export_sample.json \
  --portfolio tests/fixtures/portfolio.json
```
