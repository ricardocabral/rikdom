# Synthetic B3 movements fixture

`input.xlsx` is a new workbook built from scratch, with one `Movimentação` sheet
and ten invented source rows. It matches the sheet/header layout and text-date /
numeric-cell conventions confirmed locally against a user-authorized export.

All product identifiers, institution names, dates, quantities, prices, and amounts
are invented. No source workbook, rows, source filename, account information,
document metadata, or private validation output is included. The fixture is not a
redacted copy or a sample of the user's economic history.

Cases include two legitimately identical executions, a sale, income payments,
noncash transfers, and unsupported movements. Repeated/reordered imports preserve
anonymous occurrence identity; overlapping exports require explicit review.

The format supplies a movement date and institution, not an execution timestamp,
settlement timestamp, account number, or proof of complete history. The importer
preserves those gaps. Income quantities represent source entitlements, not new
units; transfer valuations are not invented cashflows. Gross/net basis is unknown.
