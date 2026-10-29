# Cross-Importer Deduplication

Different statement importers can describe the same position with different
holding IDs. Rikdom preserves those source identities by default. Optional
canonical-key matching can refresh an existing position when the source
provides enough identity evidence.

## Default identity matching

`merge_holdings` in `src/rikdom/plugins.py` first matches the holding's `id`:

- An existing ID with unchanged content is skipped.
- Changed, asserted source fields update the existing holding while preserving
  fields absent from the import. An older dated position does not replace a
  newer dated position.
- A new ID is inserted.

The same ticker can therefore appear under separate source IDs. Core does
not infer identity from tickers, ISINs, labels, asset types, or jurisdictions.
A repeated source import can be idempotent without establishing that its
holdings match those from another provider.

## Optional matching across source IDs

`import-statement --collapse-canonical` enables an additional match when the
incoming ID is new. A collapse requires all of the following:

- Both holdings carry the same explicit `metadata.canonical_key`.
- Both carry the same nonempty `account_id`.
- Exactly one existing holding matches that key and account.

Source plugins own canonical-key construction. Core reads the key as opaque
text through `holding_canonical_key` in `src/rikdom/canonical_key.py`; it does
not generate keys or interpret regional identifiers. A key alone identifies
an instrument, not an account-scoped position. Missing account evidence,
missing keys, and ambiguous candidates leave the incoming holding separate.

On a collapse, the existing holding ID is preserved so its references remain
stable. Asserted fields refresh the position and `metadata.collapsed_from`
records the incoming source ID. The import log's `holdings.collapses` records
`canonical_key`, `from_id`, and `into_id`. This is an import-time fallback,
not a pass that merges duplicate rows already stored in the portfolio.

`provenance.idempotency_key` remains source-scoped provenance; it does not
replace the key-and-account rule for holding collapse.

## Preview a proposed collapse

Use the selected importer's supported input file:

```bash
uv run rikdom import-statement \
  --portfolio data/portfolio.json \
  --plugin '<importer>' --input '<statement-file>' \
  --plugins-dir plugins --collapse-canonical --dry-run
```

Replace the placeholders. Inspect `dry_run_diff.rows` for
`collapsed_canonical_key` and `collapsed_into_id` on proposed updates, and
check the matching account and source valuation date. A B3 or IRPF import
will not collapse merely because the ticker matches; both sources must
explicitly establish the same key and account.

Replace `--dry-run` with `--write` after reviewing the proposed changes.
See [import a statement](../how-to/import-a-statement.md) for the full workflow.

## When identity evidence is incomplete

Use one ongoing source per position and treat other statements as audit
inputs until you can establish shared identity. Inspect previews for unexpected
new holdings before writing. A user-curated alias map or an interactive merge
review could address more cases, but neither is implemented today.
