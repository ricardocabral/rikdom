# Cross-Importer Deduplication

This page explains how `rikdom` deduplicates holdings, why importers from
different sources can produce duplicate rows for the same underlying
asset, and the options available today for collapsing them.

## How merge works today

`src/rikdom/plugins.py:merge_holdings` keys off the holding's top-level
`id`:

- existing id, identical content → **skipped**
- existing id, different content → **updated** (replaces in place,
  provenance preserved)
- new id → **inserted**

There is no fuzzy match on ticker, ISIN, CNPJ, label, or asset_type_id.
Every importer is responsible for minting its own holding ids.

## Why duplicates happen across importers

Each importer chooses its own id namespace. A few examples shipped in
this repo:

| Importer | Sample id | Stable across | Notes |
| --- | --- | --- | --- |
| `csv-generic` | `new-aapl` (user-supplied) | whatever the user chooses | the CSV is the source of truth |
| `charles-schwab` | `schwab:abcd-1234:pos:vti` | account + ticker | brokerage-account scoped |
| `b3-consolidado-mensal` | `b3:btg-pactual:12345:posi-o-a-es:brpetracnpr6` | broker + account + ISIN | broker-account scoped |
| `irpf-xml` | `irpf-0301-tk-bbdc4` | year-agnostic, ticker / CNPJ / bank-acct / hash | declaration-scoped |

These id schemes do not collide with each other (the namespace prefix
keeps them apart), and that is deliberate: each importer can re-run
idempotently against its own historical output.

But the same underlying asset — say, BBDC4 held at the BTG account that
shows up in *both* a B3 monthly export *and* an IRPF declaration — will
land in `portfolio.json` twice, once with id
`b3:btg-pactual:12345:posi-o-a-es:brbbdcacnpr8` and once with
`irpf-0301-tk-bbdc4`. The merge pass has no way to know they are the
same thing.

## Options

The five options below trade off blast radius, manual effort, and
historical compatibility differently. None of them is wired in today —
this page is a design discussion to inform a follow-up implementation.

### A. Canonical-key metadata + downstream collapse pass

Every importer additionally writes a stable `metadata.canonical_key`
(e.g. `br:acao:bbdc4`, `br:fund:30934757000113`, `us:stock:vti`). A new
post-merge pass collapses holdings that share a canonical key, picking
the most recent / most authoritative source.

- **Pros:** importers stay independent; collapse is a separate, auditable
  step; preserves per-source provenance until the user chooses to
  collapse.
- **Cons:** every importer needs to be updated to emit the field;
  collapse policy ("which source wins?") is non-trivial.
- **Effort:** medium. New CLI subcommand or `transform`-phase plugin.

### B. Reconciliation phase that proposes merges

Extend `src/rikdom/reconciliation/` to detect probable duplicates
(matching ticker, ISIN, fund CNPJ, etc.) and emit findings rather than
silently merging. The user reviews and approves merges via a new CLI
flow.

- **Pros:** safe by default (no silent data changes); fits the existing
  reconciliation surface; can surface near-duplicates that a strict
  canonical key would miss.
- **Cons:** interactive — slows down repeat imports; needs a user
  experience for approving / rejecting merges.
- **Effort:** medium-high.

### C. Provenance-based dedup via `idempotency_key`

The `plugin-statement` schema already defines
`provenance.idempotency_key` on holdings. Make every importer set it to
a canonical fingerprint (e.g. `br_acao_bbdc4`). Extend `merge_holdings`
so that, when two holdings share an `idempotency_key`, the second
**updates** the first instead of inserting alongside it.

- **Pros:** a small, well-scoped change to the merge logic; reuses
  existing schema; backward-compatible with portfolios that have no
  `idempotency_key` set.
- **Cons:** requires every importer to opt in; "update wins" semantics
  drop the older row's source attribution.
- **Effort:** low (engine) + medium (per-importer rollout).

### D. Shared `rikdom.identifiers` helper for canonical ids

Ship a helper that mints canonical ids like `br_acao_bbdc4`,
`br_fund_30934757000113`, `us_stock_vti`, and migrate every importer to
use it as the holding's primary `id`. One-shot migration: rewrite
existing portfolios via a new `migrate` step.

- **Pros:** simplest possible model — no second key, no canonical pass;
  ids are self-describing.
- **Cons:** breaking change for existing data; loses per-source
  scoping (e.g. you can no longer separately track "VTI at Schwab" vs.
  "VTI at IBKR"); requires a migration.
- **Effort:** high (migration risk, downstream rewrites).

### E. User-curated alias map

Add `data/holding_aliases.json` mapping importer-specific ids to a
canonical id chosen by the user. A post-import pass collapses holdings
according to the map.

- **Pros:** zero magic, fully explicit, trivial to audit; works around
  any tricky case (e.g. holdings that *shouldn't* collapse despite
  matching tickers, like separately-tracked tax lots).
- **Cons:** entirely manual; no help for users with hundreds of
  positions.
- **Effort:** low.

## Recommendation

For this codebase, **A + C in combination** is the most defensible path:

1. Add `metadata.canonical_key` to every importer (cheap, additive,
   no schema changes needed since `metadata` is open).
2. Teach `merge_holdings` to fall back to `canonical_key` (or
   `provenance.idempotency_key`) when ids do not match. Existing
   portfolios keep working; new imports start to collapse.
3. Surface decisions in the import dry-run: "would merge `irpf-…` into
   existing `b3-…` (canonical_key=`br:acao:bbdc4`)" — opt-in via
   `--collapse-canonical` until the behavior is well understood.
4. Optionally add E (alias map) for the long tail of cases that need
   manual override.

This preserves importer autonomy, doesn't force a destructive
migration, and lets users keep separately-scoped views (e.g. holdings
per brokerage account) when that's what they want.

## Today's workaround

Until any of the above lands, two pragmatic patterns work:

- **Pick one importer per asset class** — e.g., use `b3-consolidado-mensal`
  as the ongoing source for B3-listed positions and treat `irpf-xml`
  purely as a year-end audit / bootstrap, not a recurring source.
- **Inspect the dry-run before writing.** `import-statement --dry-run`
  prints the proposed merge plan with `inserted` / `updated` / `skipped`
  counts; if you see unexpected `inserted` rows for assets you already
  have, halt and decide before writing.
