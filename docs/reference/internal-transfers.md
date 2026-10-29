# Explicit internal cash transfers

Portfolio performance excludes a reviewed pair of cash movements between two
accounts in the portfolio. It never pairs rows by similar amounts, dates, notes,
account names or importer conventions. Unmarked historical transfers keep the
legacy external-flow treatment and disclosed approximate returns.

Both activities carry identical `metadata.rikdom_internal_transfer` evidence:

```json
{
  "version": 1,
  "pair_id": "bank-move-17",
  "review": {
    "status": "reviewed",
    "source": "Both bank statements",
    "reviewed_at": "2026-02-02T00:00:00Z"
  }
}
```

These objects require exactly the shown keys. `version` is the integer 1;
`pair_id` and review `source` are nonempty strings, and `reviewed_at` is an ISO
datetime with an explicit timezone. `pair_id` is a durable identity for one
movement; do not reuse it for a later transfer. This evidence records a supplied
review assertion. It does not prove the completeness of either bank statement.

A supported pair requires all of the following on the effective ledger:

- Exactly two posted activities: one `transfer_out` and one `transfer_in`.
- Two distinct, nonempty activity IDs and distinct explicit `account_id` values.
- The same UTC instant, identical positive native cash amounts and the same
  uppercase three-letter currency. Equivalent timezone offsets are accepted.
- No `holding_id`, transferred tax-lot references, nonzero quantity, corporate
  action or basis adjustment.
  Embedded fees/taxes must be absent or zero in the transfer currency; record
  charges separately. Negative amounts, zero amounts and nonfinite numbers do
  not establish a pair.
- No conflicting activity-ID or idempotency-key replay. Identical replays collapse
  before matching; import-run IDs and ingestion timestamps do not create new legs.

Apply corrections through the existing immutable correction contract. Matching
uses the effective replacement IDs after superseded rows have been removed.
A cancelled replacement removes that leg; its remaining posted counterpart then
fails verification. Two cancelled legs produce no cashflow. Existing correction
integrity errors still reject the ledger.

Validation uses the full effective ledger before period filtering. A counterpart
outside the period cannot be hidden to make a partial movement look internal.
Performance bookend windows include both endpoints. Evidence and diagnostics are
limited to pairs/claims touching that window; malformed dates remain relevant
because their exclusion cannot be established.

## Boundary behavior and output

A verified pair contributes zero portfolio external cashflows. Its two legs
remain available for account and strategic-bucket Dietz/XIRR calculations; each
account keeps its signed flow. Cash-only legs have no holding reference and use
the existing `__unallocated__` strategic bucket. No holding allocation is inferred.
Missing FX needed by a scoped leg makes that scope's return unavailable. A
same-native-currency foreign pair requires no portfolio conversion because its
native movements cancel at the same instant; foreign position cost attribution
remains unsupported by FIFO.

A malformed claimed pair leaves the rows external and sets portfolio TWR/MWR to
null with diagnostics. The residual growth/profit bridges are unavailable.
Scoped results also fail closed for that period. Unmarked transfers retain their
legacy approximate behavior, and prevent an exact residual bridge. In-kind,
cross-currency and asynchronous pair claims remain unsupported.

`performance_result_to_dict` adds detached `internal_transfers` provenance:

```json
{
  "version": 1,
  "status": "verified",
  "pairs": [{
    "pair_id": "bank-move-17",
    "activity_ids": ["out", "in"],
    "account_ids": ["a", "b"],
    "effective_at": "2026-01-16T12:00:00+00:00",
    "amount_native": 20,
    "currency": "BRL",
    "review": {
      "status": "reviewed",
      "source": "Both bank statements",
      "reviewed_at": "2026-02-02T00:00:00Z"
    }
  }],
  "issues": []
}
```

IDs/accounts are ordered outgoing then incoming. `status` is `verified` when
in-window pairs pass, `none` when there is no in-window pair/claim, and
`unavailable` when any relevant claim fails. `issues` records `pair_id`,
`activity_ids` and `reason`. Before a usable performance window can be selected,
the field may be an empty object. Pair status describes pairing evidence only;
inspect return, FX and bridge availability separately. It never certifies all
transfers or the complete history. Published provenance can be edited by a
consumer without changing the input ledger or subsequent serialization.

The profit bridge publishes the same accepted provenance. Reviewed FIFO keeps
both reporting-currency cash legs, with negative outgoing and positive incoming
cash, so the aggregate cash movement is zero and position quantities stay intact.
It still requires reviewed opening/closing cash, positions, lots and complete
period history. Opening-instant activity ambiguity and foreign FIFO constraints
continue to make decomposition unavailable.
