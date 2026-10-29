# Calendar performance

`rikdom performance` includes `calendar_performance`. Offline report JSON carries
that identical object under `sections.performance.calendar_performance`; full and
fallback HTML render its monthly and yearly tables. Calculations use local inputs
and the existing performance engine. JavaScript only formats supplied facts.

## Windows and coverage

Calendar boundaries are midnight UTC on the first day of a month or year. A
`complete` row covers the entire calendar period. A `partial` row covers a
bookend clipped to the first/last supplied valuation or explicit `--since` /
`--until` boundary. Partial coverage is not an annualized calendar-period claim.
Date-only `--since` is midnight UTC; date-only `--until` includes that entire UTC
day, matching the CLI window convention. To request an exact calendar ending,
use the next period's midnight timestamp, such as `2027-01-01T00:00:00Z`.

Every row requires exact valuations at both its endpoints. A nearby snapshot is
never substituted. Missing endpoints leave a visible `unavailable` row with
warnings and a null `performance`. Malformed or duplicate valuation timestamps
make calendar history unavailable. Explicit historical valuation replay replaces
recorded snapshots; missing or stale replay evidence never falls back to them.

The cashflow interval is **(start, end]**. Opening valuations are assumed to be
post-flow; a flow exactly at a shared boundary belongs to the ending row, once
per monthly or yearly table. The first row excludes flows at its opening instant
because that capital is already in its opening valuation. Effective ledger
corrections are resolved before selecting rows. Before/after flow valuations use
the same interval, with their original source evidence retained in the payload.
The legacy selected-period calculation retains its existing inclusive semantics.

## JSON fields

The object contains `status`, `scope`, `timezone`, `cashflow_interval`,
`opening_valuation`, `warnings`, `monthly`, and `yearly`. Selected flow-valuation
and historical-replay evidence are included when supplied. Each row contains:

| Field | Meaning |
| --- | --- |
| `label` | `YYYY-MM` or `YYYY`, in UTC |
| `period_start`, `period_end` | Exact row endpoints |
| `coverage` | `complete` or `partial` calendar coverage |
| `status` | `available` or `unavailable` selected return |
| `performance` | Serialized core result, or null for missing bookends |
| `warnings` | Calendar availability diagnostics |

A calculated row preserves the selected TWR method, period-return basis, legacy
Dietz fields, annualized XIRR basis, cashflow count, growth bridge, FX evidence,
valuation status, benchmark comparison and source provenance supplied by the core
calculator. Missing dated FX propagates to unavailable returns. Recorded
valuations retain `recorded_unverified` status; having exact timestamps does not
verify their price or FX history. A selected Modified Dietz result remains an
approximation and keeps its fallback explanation. Read the result warnings and
quality evidence as well as calendar coverage.

Yearly rows are calculated directly from their own valuations and flows. Monthly
returns are never added to obtain a yearly return. Annualized XIRRs are never
summed or multiplied. Period-specific reviewed FIFO opening-lot evidence is not
invented for calendar rows.

Calendar tables support portfolio scope. CLI account/bucket output explicitly
marks calendar tables `unavailable_for_scope`; instrument output retains its
native-currency contract. Interactive report date or dimension filters suppress
performance tables until reset because filtered historical attribution has not
been asserted. Generate a new report with explicit calculation dates to obtain
calendar rows for another window.

Verified internal cash pairs are classified against the entire effective ledger
before calendar slicing. They do not appear as portfolio external flows and
retain their reviewed pair provenance. Conflicting replay identities outside a
calendar row can invalidate a claimed pair inside it; such rows remain
unavailable. The portfolio contributions display follows the same full-ledger
classification. Scoped account/bucket calculations still retain individual legs
and require their own FX conversions.
