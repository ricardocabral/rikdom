# btg_wm_conta_internacional

Pluggy `source/input` plugin that imports holdings and activities from BTG WM "conta internacional" monthly statements.

## Expected input

- Primary: PDF monthly statement exported by BTG WM / DriveWealth
- Test/fixture mode: extracted `.txt` text (same `pdftotext -layout` format)

## Notes

- Requires `pdftotext` (Poppler) when input is PDF.
- Emits:
  - `holdings` from the `HOLDINGS` section
  - `activities` from both `ACTIVITY` and `SWEEP ACTIVITY` tables
- Uses USD as `base_currency` and validates parsed holdings sum against the statement `Ending Account Value`.
- Preserves signed sale quantities and repeated execution rows. Opening-balance
  reconstruction applies event direction once, including broker-signed debits.
- Rejects unresolved activity numeric cells, including incomplete wrapped money
  amounts. Recover ambiguous rows from the original PDF before importing; a
  partially parsed activity table must not silently pass as a complete statement.

## CLI example

```bash
uv run rikdom import-statement \
  --plugin btg_wm_conta_internacional \
  --plugins-dir plugins \
  --input ~/Downloads/btg-wm-monthly-statement.pdf
```

## Received income and withholding

`DIV` rows are signed posted dividends with
`metadata.rikdom_income = {"version": 1, "amount_basis": "unknown"}`. The supported
statement cash amount does not establish gross/net. `DIVNRA` rows are separate
signed `tax_withheld` events (subtype `withholding_tax`), including refunds.
Missing attached withholding is not zero, and separate tax rows are not linked
to dividends. Other income/interest codes remain unsupported `other` events in
diagnostics; an accrued-interest heading does not create a received payment.

Existing activity and opening-balance IDs are preserved. Source identity metadata
allows preflight to require review when a legacy stored withholding row still
uses the old `fee` classification. Repeated unchanged imports add no events.
Synthetic openings remain position observations based on the existing period
quantity calculation; signed income/tax rows do not create sweep units or prove
cash availability, historical completeness or received income on the opening date.
