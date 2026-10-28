# charles-schwab

Pluggy `source/input` plugin that imports Charles Schwab CSV statement exports into Rikdom canonical statement JSON.

## Supported Input (v1)

Single CSV containing mixed record types with this header set:

- `record_type` (`account`, `position`, `cash`, `transaction`)
- `account_number`, `account_name`, `statement_date`, `currency`
- Position rows: `security_type`, `symbol`, `description`, `quantity`, `market_value`
- Cash rows: `cash_balance`
- Transaction rows: `date`, `action`, `symbol`, `description`, `quantity`, `amount`, `fees`, `reference_id`

Header matching is case-insensitive and tolerant of spaces/punctuation.

## Mapping Notes

- `provider` is always `charles-schwab`
- `metadata.accounts` captures account metadata discovered in the file
- Position + cash rows map to canonical `holdings`
- Transaction rows map to canonical `activities`
- Supported transaction mappings: `buy`, `sell`, `dividend`, `interest`, `income`, `tax_withheld`, `fee`, `transfer_in`, `transfer_out` (fallback `other`)
- Deterministic `id`/`idempotency_key` values are generated for idempotent re-runs

## Income evidence

Dividend, interest, and generic income keep the source amount's sign, including
negative corrections. Explicit withholding/tax action labels map to separate
`tax_withheld` events before dividend/interest matching; refunds keep their sign.
Classification uses the action field, not the instrument description. Bounded
labels avoid treating `TAXF` or `Tax-Exempt Bond` as a tax action.

The supported CSV dialect does not establish whether `amount` is gross or net.
Income therefore declares `metadata.rikdom_income` as
`{"version": 1, "amount_basis": "unknown"}`. Reports retain this uncertainty.
Missing withholding is never replaced with zero or inferred from a tax event.
Available income fees retain their sign, including explicit zero; a blank fee
remains absent. The dialect's `currency` applies to transaction amounts and fees,
with the existing USD default for omitted currency.

Anonymous IDs and idempotency keys retain the original fingerprint convention,
including its historical amount-sign normalization. Corrected money and event
types can therefore update the same source identity rather than create a duplicate.
If two rows share a legacy identity but have different content (for example,
anonymous +10 and -10 dividends on the same date), the import fails rather than
dropping one. Resolve the source's distinct reference IDs, or use the
[normalized-input workflow](../../docs/how-to/import-a-statement.md) with reviewed,
confirmed event IDs; do not invent source references.

Preview reimports of previously imported income: ordinary source rows may update,
while corrected or superseded rows retain the existing ledger protections. Use an
[auditable correction](../../docs/how-to/enter-and-correct-activities.md) or a
reviewed normalized statement when repairing stored evidence.

## Known Gaps (v1)

- No PDF parsing
- No OFX support yet
- No advanced corporate-action expansion (splits, mergers, spin-offs)
- Assumes U.S. jurisdiction defaults for instruments unless additional fields are provided

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin charles-schwab \
  --plugins-dir plugins \
  --input plugins/charles-schwab/fixtures/taxable-mixed/input.csv \
  --portfolio tests/fixtures/portfolio.json
```

## E2E Runner (isolated portfolio workspace)

Run from repo root:

```bash
plugins/charles-schwab/run-e2e.sh
```

- Uses a temporary portfolio directory under `/tmp` (does not touch `data/`)
- Imports twice to verify idempotency
- Set `KEEP_E2E_DIR=1` to keep generated artifacts for inspection
