# BTG investment PDF

Imports full-label Brazilian investment statements with `pdftotext -layout`.
The pure `parser.parse_statement(text, source_path)` interface returns positions,
reported acquisition observations and full statement section evidence. Each asset
category and the account gross total must reconcile or parsing raises `ValueError`.

Instrument IDs combine the normalized account with explicit instrument codes,
fund class CNPJ or government-security maturity and custody section. Subscription
rights remain distinct instruments. Acquisition detail rows are observations of
remaining lots, and do not generate historical purchases or tax lots. Fund adjusted
purchase values are labeled separately from reported fixed-income purchase values.

The parser does not update existing portfolio IDs or zero absent instruments.
The importing workflow must map instrument identities and retire absent holdings
only within the successfully reconciled account and complete statement scope.
Full-label monthly statements with compact horizontal fixed-income tables and
annual statements are supported. Legacy abbreviated-label statements are rejected
rather than partially imported. Every successful parse covers the whole account
position summary; unresolved category totals raise an error.

Reported acquisition observations support fund detail rows and the fixed-income
block layout. Older compact acquisition detail tables remain in section evidence
for separate recovery. Sections also retain structured movement rows with raw
columns, numeric cells, source page and original text. Lending shares are already
part of owned positions; only explicitly reported accumulated lending income is
added as a separate receivable.

PDF input requires Poppler's `pdftotext`. Text input must retain layout spacing.
All amounts are BRL; full precision is retained during reconciliation and each
reported price is kept separately from broker gross market value.
