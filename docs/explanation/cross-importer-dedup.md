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

## What is wired in today

`rikdom` ships **option A combined with option C**, opt-in:

1. Every imported holding gets a `metadata.canonical_key` (e.g.
   `br:acao:bbdc4`, `us:stock:vti`, `cash:brl`). The key is derived
   centrally in `src/rikdom/canonical_key.py:assign_canonical_keys` from
   `(asset_type_id, identifiers, jurisdiction)`, so importers do not
   need to be modified one by one. An importer can still override by
   emitting its own `metadata.canonical_key`.
2. `merge_holdings` accepts `collapse_canonical=True`. When set, an
   incoming holding whose `id` does not match anything existing falls
   back to a canonical-key lookup; if a match is found, the existing
   slot is updated in place (the existing id is preserved so external
   refs do not break) and the import run records a `collapsed_from` list
   in `metadata`.
3. The CLI exposes this via `import-statement --collapse-canonical`. The
   default behavior is unchanged: without the flag, ids are still the
   only dedup key and importer outputs do not collide silently.
4. Dry runs surface the decisions: each row in `dry_run_diff.rows` that
   collapses includes `collapsed_canonical_key` and `collapsed_into_id`,
   and the merge log records a `collapses` list under `holdings`.

Holdings without a derivable canonical key (free-text labels, opaque
positions like `tesouro_direto` rows that lack a stable identifier) are
left untouched and continue to dedup by id only.

## Options considered

The five options below trade off blast radius, manual effort, and
historical compatibility differently.

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

## Why A + C

The shipped path preserves importer autonomy (each one keeps its own id
namespace), doesn't force a destructive migration, and lets users keep
separately-scoped views (e.g. holdings per brokerage account) when that
is what they want — `--collapse-canonical` is opt-in per import, and
holdings without a canonical key are unaffected.

Option E (user-curated alias map) remains a sensible follow-up for the
long tail of cases that need manual override (e.g. holdings that
*shouldn't* collapse despite matching tickers).

## Recipe: collapsing a B3 holding into an IRPF import

```bash
uv run rikdom import-statement \
  --portfolio data/portfolio.json \
  --plugin irpf-xml \
  --input ~/Downloads/IRPF-A-2025.xml \
  --plugins-dir plugins \
  --collapse-canonical \
  --dry-run
```

Look for `dry_run_diff.rows[*].collapsed_canonical_key` in the output to
confirm the proposed merges before re-running with `--write`.

## Fallback workarounds

If you don't want to opt in to `--collapse-canonical`, two pragmatic
patterns still work:

- **Pick one importer per asset class** — e.g., use `b3-consolidado-mensal`
  as the ongoing source for B3-listed positions and treat `irpf-xml`
  purely as a year-end audit / bootstrap, not a recurring source.
- **Inspect the dry-run before writing.** `import-statement --dry-run`
  prints the proposed merge plan with `inserted` / `updated` / `skipped`
  counts; if you see unexpected `inserted` rows for assets you already
  have, halt and decide before writing.
