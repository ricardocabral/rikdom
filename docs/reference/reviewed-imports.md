# Reviewed recurring imports

`import-statement --review-file review.json` stores reviewed enrichment separately
from the normalized source statement. Later imports of that raw statement apply
the saved enrichment without requiring the review file again. Preview with
`--dry-run`; add `--write` to persist the validated candidate.

```sh
rikdom import-statement --plugin normalized-statement-json \
  --input statement.json --review-file review.json --data-dir data --dry-run
```

## Review document version 1

```json
{
  "version": 1,
  "decisions": [
    {
      "id": "account-and-date-a",
      "collection": "activities",
      "entity_id": "a",
      "changes": {
        "account_id": "account-a",
        "holding_id": "h",
        "trade_at": "2026-01-02T12:00:00Z"
      },
      "evidence": {"kind": "user_declaration", "source_ref": "review-notes:42"}
    }
  ]
}
```

A decision is bound to its provider, collection, stable entity ID and exact
normalized source revision. Supported collections are `activities`, `holdings`,
`tax_lots`, `statement_observations`, and `diagnostics`. For diagnostics, use
`entity_id: "statement"` and patch the normal import diagnostic fields, such as
`history_coverage`. Evidence requires `kind: "source"` or `"user_declaration"`
and a nonempty `source_ref`. The effective enriched row must satisfy the existing
portfolio schema; diagnostics must satisfy the import diagnostics contract.

One active decision per provider/entity is supported. Group its reviewed fields
in one `changes` object. Nested objects merge recursively; lists replace as a
whole. A decision cannot patch identity, provenance or correction extensions,
replace source/canonical identity metadata, or remove metadata using a nonobject.
Stable account/holding bindings, timing evidence and coverage remain explicit
user assertions rather than facts inferred from transaction totals.

Reusing the identical review document is idempotent. To replace a review, retire
it with `accept_source` and use a new decision ID; the two operations can be in
the same document. Existing portfolios need no migration. Values manually edited
before review tracking are not automatically converted into reviewed decisions;
submit an explicit decision to protect them on recurring imports.

## Contradictions and explicit resolution

The preview publishes `preflight.review.source_revision`, applied decision IDs,
and conflicts with the decision/version/entity, previous and incoming source,
changed fields, reviewed overlay, and affected result categories. A contradiction
blocks both portfolio and import-log writes. Result categories are conservative
invalidation guidance (valuation, coverage, reconciliation, performance and
transfer identity), not computed numerical deltas or a saved-run dependency graph.

A changed previously asserted source value invalidates the entity's active
review. A newly asserted source field also conflicts when it disagrees with a
review-only value. Accepted new assertions join a separate `accepted_source`
observation baseline, so subsequent changes to those facts also conflict. Omitted
optional source fields do not assert retraction: their accepted financial values
and evidence remain in the effective reviewed row, even across multiple partial
imports. Imports without active reviews retain their existing refresh behavior.
Source identity metadata changes conservatively require re-review. A review of
statement diagnostics applies to that provider's incoming diagnostics; a changed
statement or coverage declaration can therefore require re-review.

After inspecting the preview, provide its exact source revision:

```json
{
  "version": 1,
  "resolutions": [
    {
      "decision_id": "account-and-date-a",
      "source_revision": "<preflight.review.source_revision>",
      "action": "keep_review",
      "reason": "Checked the revised broker event against the execution receipt"
    }
  ]
}
```

`keep_review` accepts the new source baseline and explicitly reapplies the saved
overlay. `accept_source` retires the overlay and uses source values. It also
removes review-only leaves absent from the source, including nested holding
metadata, while preserving unrelated enrichments. Both actions increment the
decision version and retain its former version and resolution evidence. Stale,
duplicate, unknown or absent-target resolutions fail before canonical writes.

Renamed incoming IDs that reuse a reviewed row's idempotency key are rejected;
a provider change colliding with a reviewed entity is likewise rejected. There
is no implicit identity migration. With `--collapse-canonical`, differently named
holding rows that would collapse into an active reviewed holding are rejected
before writes, using the existing merge's exact account/canonical-key match and
same-batch merge sequence. Canonical similarity does not authorize migrating a
reviewed identity. Ambiguous ID/key matches and duplicate
incoming identities also fail before canonical writes. Existing source-only
refresh and linked activity corrections retain their original contracts. An
unchanged raw reimport of a reviewed correction target remains permissible;
a destructive change to a protected correction ledger still requires the
existing correction workflow.

## Retained versions and recovery

Successful imports retain `portfolio.extensions.rikdom_reviewed_imports` version 1:

- `initial_effective`: the portfolio before this feature first observed an import.
- `decisions`: current reviewed records, original `source`/`source_revision`,
  accepted source observations (`accepted_source`/`accepted_source_revision`),
  review versions and history.
- `revisions`: normalized `source`, corresponding `reviews`, and the complete
  `effective` portfolio projection for every distinct accepted state.
- Each revision has a monotonic `version`, `source_revision` and `content_hash`.

Effective projections exclude the retention extension itself to avoid recursive
history; empty extension containers are normalized away. Source observations
retain run provenance. Revision hashes use sorted JSON and exclude run ID and
ingestion timestamp, so changing only those does not create another revision.
Unchanged reimports retain the existing canonical provenance and history. Accepted source observations accumulate without rewriting the original review
baseline or incrementing the review decision version. Explicit resolutions still
increment that version. Prior accepted observation baselines remain in each
retained revision's `reviews`, and exact prior normalized source/effective inputs
remain readable
after a source refresh; original statement files are not copied into this state.

This is additive local evidence retention, not a backup or a rollback command.
It grows with accepted changes; there is no automatic pruning. Saved calculations
must still capture their selected inputs using the analysis-run/bundle workflow.
Preexisting history from before tracking began cannot be reconstructed.

## Explicit internal transfers

Reviewed activity metadata can include the existing
[`rikdom_internal_transfer` cash-pair contract](internal-transfers.md). Both legs
must carry the same explicit evidence. Review storage does not infer pairs from
amounts/dates or introduce a second convention. Changed source facts on a reviewed
leg block import pending resolution; retiring that review removes its pair claim.
The existing resolver evaluates the corrected effective ledger and discloses
missing, conflicting or unsupported endpoints. Portfolio calculations suppress
only valid internal pairs; account calculations retain the boundary flows.

## Library boundary

`rikdom.reviewed_imports` exposes three functions for the existing import pipeline:

1. `prepare_reviewed_import(portfolio, source, review=None, *, collapse_canonical=False)`
   returns a detached
   effective statement, review preview and pending state. It does not mutate inputs.
2. `reviewed_merge_base(portfolio, state)` returns a detached merge candidate with
   explicitly retired overlay leaves restored to their source values or absence.
3. After preflight, ordinary merges, reconciliation and financial checks,
   `retain_reviewed_import(candidate, source, state)` retains the accepted revision
   in that candidate. Save only after every required check succeeds.

Callers must not persist pending state from a blocked preview. The CLI follows
this order and writes the portfolio through the existing atomic JSON writer.
