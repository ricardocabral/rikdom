# Local market events

`rikdom.market_events` reads independent version 1.0 JSON files containing
announced distributions and splits. It provides deterministic lookup, read-only
review previews, and an explicit apply function that returns a detached portfolio.
It performs no network acquisition or persistence. Portfolio schema 2.0.0 is
required for applying either supported path; migrate older portfolios explicitly.

An announcement is not entitlement or a payment confirmation. The module never
creates a payment from an announcement, calculates available cash, reconstructs
positions, updates holdings or tax lots, or adjusts market prices. It cannot
establish distribution yield or calendar completeness.

## File contract

The root contains exactly `contract_version: "1.0"` and `events`, an array.
Each event contains exactly:

| Field | Contract |
| --- | --- |
| `id` | Stable nonblank economic event identity within the source file. Preserve it across revisions and imports. |
| `kind` | `distribution` or `split`. |
| `instrument` | Exact `namespace`, `id`, and uppercase three-letter `currency`. No ticker-only matching. |
| `adjustment_basis` | `unadjusted`, `split_adjusted`, or `total_return_adjusted`. Only `unadjusted` can be applied. |
| `coverage` | Explicit UTC `start` and `end`, inclusive. Describes the supplied evidence window, not complete exchange or provider coverage. |
| `license` | Nonblank `name` and `uri`. A declaration from the file author, not independent verification of redistribution rights. |
| `revisions` | Nonempty array forming one root and a single nonforking correction chain. |

Every revision contains exactly `id`, `effective_at`, `retrieved_at`, `source`,
`supersedes`, and its kind-specific fields. Revision IDs are unique across the
file. `supersedes` is null for the root or an existing revision ID of that event.
Retrieval time must strictly increase along the chain; references may appear in
any array order. The entire file is rejected for a malformed chain.

Split revisions add a finite positive `ratio`: post-event units per pre-event
unit. Distribution revisions add `per_unit` (money with `amount` and `currency`,
or null), `record_at` (UTC timestamp or null), and `payment_at` (UTC timestamp or
null). Per-unit amounts are finite and nonnegative. An explicit zero is zero;
null is unknown. Record and payment dates describe the announcement only.

All timestamps require explicit UTC `Z` or `+00:00`. Effective time must fall
inside coverage. Retrieval may precede effective time because announcements can
be prospective. Unknown fields, unsupported versions, duplicate keys/IDs,
booleans used as numbers, NaN/infinity, non-string object keys, and Python-only
in-memory values such as tuples are rejected. No malformed event is skipped.

## Lookup and knowledge cutoff

```python
from rikdom.market_events import load_market_events

events = load_market_events("data-sample/market-events/us.json")
selection = events.lookup(
    "synthetic-us-distribution",
    as_of="2026-02-01T00:00:00Z",
    retrieved_before="2026-01-05T00:00:00Z",
)
```

`lookup` returns `status`, `reason`, normalized query timestamps, event metadata,
the selected `revision`, and `superseded` evidence. Retrieval cutoff is inclusive.
Omitting it uses all vintages in the file, including later corrections. Selection
uses the latest known revision, then checks effective time. A revised future date
returns `event_not_effective`; it never revives an obsolete earlier revision.
A selection outside coverage, unknown ID, or absence of a known revision returns
`missing` with a specific reason. Output and input dictionaries are detached.

## Reviewed split

The review object contains exactly:

```json
{
  "contract_version": "1.0",
  "reviewed": true,
  "revision_id": "synthetic-us-split-r1",
  "holding_id": "h1",
  "account_id": "account",
  "source": "manual:position-statement",
  "quantity_basis": "unadjusted",
  "pre_quantity": 10,
  "post_quantity": 20
}
```

The existing holding must match the exact namespaced instrument and account.
The review explicitly asserts quantities immediately before and after this event;
current holding quantity is not evidence of the historical pre-event position.
Pre-quantity must be positive and post-quantity must match the announced ratio
within relative tolerance `1e-12` (zero absolute tolerance). This tolerance allows
floating-point arithmetic noise; it does not authorize rounding, inferred cash in
lieu, or adjusted prices. Adjusted quantities are unavailable.
Source must identify the reviewed position evidence.

A ready proposal contains one posted `split` activity with a structured
`corporate_action`, ratio, and signed quantity-delta leg. Reverse splits use
`corporate_action.kind: "reverse_split"`. It adds no money, valuation, price, or
cost-basis adjustment and changes no holding or lot. Existing same-time split
activities or split legs for that holding require manual review to avoid duplicate
imports.

### Reviewed split revisions

A provider revision can replace the currently effective split when its retained
source chain contains every previously applied source announcement exactly. A
revision is a full replacement of the original ratio and delta, never an extra
split or an incremental adjustment. For example, revising 2:1 to 3:1 for ten
original units records a replacement ratio of 3 and a delta of 20. The original
ratio 2 and delta 10 stay unchanged in the stored ledger. Only the replacement
appears in `effective_activities`; reverse splits follow the same rule.

Revisions require a version 1.1 review with two additional fields:

```json
{
  "contract_version": "1.1",
  "reviewed": true,
  "revision_id": "synthetic-us-split-r2",
  "holding_id": "h1",
  "account_id": "account",
  "source": "manual:revised-position-statement",
  "quantity_basis": "unadjusted",
  "pre_quantity": 10,
  "post_quantity": 30,
  "effective_at": "2026-01-10T00:00:00Z",
  "reviewed_at": "2026-01-20T00:00:00Z"
}
```

`effective_at` must equal the selected announcement date, including a corrected
effective date. `reviewed_at` must be at or after both the effective date and the
source retrieval date, and no later than the query's `as_of`. Both require strict
UTC timestamps. Version 1.0 remains supported for an initial split; using it to
revise an applied split returns `split_revision_review_required`.

The original `pre_quantity` must remain exactly equal across the correction
chain. A changed pre-event position returns `split_pre_quantity_changed`; a date
change does not establish a different historical position. Reviewed post-event
quantity must match the replacement ratio with the same `1e-12` relative
arithmetic tolerance. A revised future date returns `event_not_effective` until
it is effective; it never falls back to the older date.

Every revision appends an immutable activity with its own ID and an
`extensions.rikdom_correction` link to the current split leaf. The market-event
marker retains the exact source chain, review and query cutoff. Before accepting
a new revision or replay, the module checks the complete stored correction chain,
including the root and each successor. Old applied reviews replay as noop after
later corrections. An unseen older revision, an unrelated chain, or a cutoff that
would downgrade a newer applied revision returns `stale_or_unrelated_revision`.
Changed source evidence under a retained ID returns `applied_revision_conflict`.
Applying r2 first does not count r1 as applied; an unseen r1 replay is rejected.
Holdings and accounts have independent correction chains, bound to exact
namespaced instrument identities.

This workflow supports a conservative path with no dependent tax lots. Any lot
for the affected holding, any lot linked to a related activity or correction
ancestor, or an unsupported later corporate action returns
`dependent_activity_review_required`. Incoming lots in the same import are also
checked. Review these dependencies through a separate audited migration before
retrying; this workflow does not rebuild or erase lots. Ordinary manual corporate
action corrections retain the existing guard. A caller-supplied proof flag,
changed scope, extra legs, money or modified ratio cannot bypass it: import
validation reparses the retained source chain and recomputes the exact reviewed
replacement against the current ledger.

Synthetic `split-revisions.json` and `split-revision-review.json` demonstrate the
2:1 to 3:1 correction. Apply the existing `us.json` / `split-review.json` first,
then apply these revision files to the same scratch portfolio with
`--event synthetic-us-split --as-of 2026-02-01T00:00:00Z`. Reapplying either
review afterward is a noop. No step changes holdings, prices or persisted lots.

## Reviewed observed distribution correction

The review object contains exactly:

```json
{
  "contract_version": "1.0",
  "reviewed": true,
  "revision_id": "synthetic-us-r1",
  "observed_activity_id": "observed",
  "source": "statement:reviewed-correction",
  "money": {"amount": 5, "currency": "USD"},
  "amount_basis": "gross"
}
```

`observed_activity_id` must link an existing posted dividend or interest with an
explicit source, namespaced instrument, holding and account. The holding must
still resolve and match those identities. Missing historical entitlement or a
missing payment cannot be repaired from per-unit values. Reviewed money comes
from the observed-payment correction evidence; no multiplication or date/amount
matching links announcements to payments. `amount_basis` is `gross`, `net`, or
`unknown`; zero money is valid. Currency conversion is unsupported.

The proposal copies the current payment leaf, preserves unknown metadata,
fees and withholding, sets the reviewed money and amount basis, and appends
`extensions.rikdom_correction` against the current leaf. It preserves all original
ledger entries. A new provider revision can append another explicitly reviewed
correction only when every previously applied revision of that event appears in
its retained ancestry with identical source evidence. An unseen older revision,
a file that omits the applied revision, or an unrelated replacement chain returns
`stale_or_unrelated_revision`; a retrieval cutoff cannot downgrade a newer payment.
The entire payment correction chain is checked, even when a later manual leaf has
no event marker. Exact replays of previously applied reviews still return noop.
Existing dependent tax lots or corporate actions block correction
with `dependent_activity_review_required`. Changing money does not infer a tax
correction, settlement, cash account movement, or available-cash balance.

## Preview and apply interface

```python
import json
from rikdom.market_events import preview_market_event, apply_market_event

with open("data-sample/market-events/portfolio.json") as handle:
    portfolio = json.load(handle)
with open("data-sample/market-events/split-review.json") as handle:
    review = json.load(handle)

preview = preview_market_event(
    portfolio, events, event_id="synthetic-us-split",
    as_of="2026-02-01T00:00:00Z", review=review,
)
candidate, checked_preview = apply_market_event(
    portfolio, events, event_id="synthetic-us-split",
    as_of="2026-02-01T00:00:00Z", review=review,
)
```

Both functions accept optional `retrieved_before`; preview also permits no review.
Preview returns `status: ready | unavailable | noop`, `reason`, `selection`, and
proposed `activities`. Without review it returns `review_required` and no
activities. Unavailable reasons identify missing positions, mismatched identity,
old review revision, unsupported adjustment basis, missing observed payment,
or other actionable limits. Malformed inputs raise `ValueError`.

Apply recomputes the preview against the supplied portfolio. It refuses
unavailable proposals and merges ready proposals through `merge_activities`.
It returns `(candidate_portfolio, preview)` without changing the input. The host
must validate the complete candidate and persist it with its normal atomic
canonical writer. Previews never authorize a stale cached proposal.

Stable generated IDs and idempotency keys bind the source event to its holding
or observed payment. Repeating an applied review is a noop, including replaying
an old payment correction after a newer correction. A changed review under an
already-applied identity is unavailable. Reusing a revision ID with different
announcement evidence is rejected at application. Files must retain stable IDs;
this module does not deduplicate unrelated provider identities or infer that two
notices describe the same economic event.

## Synthetic examples and limits

`data-sample/market-events/br.json`, `us.json`, and `jp.json` demonstrate BRL,
USD, and JPY with deliberately synthetic namespace and instrument identifiers.
They claim no actual Brazilian, US, or Japanese security coverage, exchange
calendar, holiday rule, issuer announcement, payment date, or data-provider
license. The fixture license applies only to authored synthetic examples.
The US file also contains a split; `portfolio.json`, `split-review.json`, and
`distribution-review.json` provide runnable apply evidence. Do not apply these
fixtures to an actual portfolio.

No provider plugin or remote enrichment acquisition is included. Future
providers must preserve this strict event identity and revision contract; raw
provider announcements must not bypass host review or become received income.

## CLI workflow

All commands use explicit local files. They do not bootstrap a workspace, access
providers, infer entitlement, or fetch prices. Lookup and preview preserve input
bytes. `apply` also previews unless `--write` is supplied; `--dry-run` overrides
`--write`. Applying validates the current and proposed portfolio and uses the
canonical atomic JSON writer. A no-op replay does not rewrite the portfolio.
The ledger carries the action/review provenance; this command does not append a
separate import log, rebuild holdings/tax lots, or rewrite snapshots/prices.

```bash
uv run rikdom market-events lookup --input data-sample/market-events/us.json \
  --event synthetic-us-split --as-of 2026-02-01T00:00:00Z

uv run rikdom market-events preview --input data-sample/market-events/us.json \
  --event synthetic-us-split --as-of 2026-02-01T00:00:00Z \
  --portfolio data-sample/market-events/portfolio.json \
  --review data-sample/market-events/split-review.json

# Copy the synthetic portfolio to a scratch path before trying --write.
uv run rikdom market-events apply --input data-sample/market-events/us.json \
  --event synthetic-us-split --as-of 2026-02-01T00:00:00Z \
  --portfolio /tmp/reviewed-portfolio.json \
  --review data-sample/market-events/split-review.json --write
```

Source event/review files cannot alias the written portfolio, including symlinks
and hard links. Lookup/preview can return missing or unavailable evidence as
successful JSON; applying an unavailable action exits nonzero without a write.
Invalid files or failed persistence also exit nonzero. No background action is
scheduled. Both application paths require explicit schema 2.0.0 adoption because
older readers must not ignore immutable correction history.
