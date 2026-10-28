# Income plan version 1

An income plan records reviewed announcements, separate scenario estimates,
explicit payment links, and declared cost evidence. It never creates activities,
holdings, entitlements from current positions, FX conversions, or realized returns.
Use a local JSON file or `portfolio.extensions.rikdom_income_plan`. The standalone
contract is [income-plan.schema.json](../../schema/income-plan.schema.json).

## Input

`version` must be the integer `1`. The optional arrays `announcements`, `estimates`,
`payment_links`, and `cost_bases` default to empty. Unknown fields fail validation.
Numbers must be finite JSON numbers, not booleans. Dates are real ISO calendar
dates (`YYYY-MM-DD`). IDs and evidence references must contain non-whitespace text.

A `source` or `entitlement_source` is explicit evidence:

```json
{"kind": "manual", "reference": "Reviewed statement 2026-01", "as_of": "2026-01-31"}
```

`kind` is `manual`, `file`, or `provider`. A reference can be a local file identifier,
a source URL, or a written manual declaration. The calculator never retrieves it.
`as_of` describes the evidence date; it is not an inferred payment date or coverage
end. Record revised evidence explicitly.

A `scope` contains one or more of `account_id`, `asset_type_id`, `holding_id`,
`instrument` (a nonempty JSON object), and `source_system`. All supplied dimensions
must exactly match historical activity dimensions. The instrument object is
compared as a whole; a ticker alone does not match a richer object. Current
holdings never fill missing activity dimensions. `source_system` matches an
activity's top-level `source_system` or `provenance.source_system`; conflicting
assertions make the source unknown. Scope references are assertions about
historical events and do not require a current holding to still exist.

Money is `{"amount": 50, "currency": "USD"}`. Currency is a three-letter uppercase
code. All plan money amounts are nonnegative; cost money must be strictly positive
or explicitly `null` when unknown. Signed actual ledger adjustments remain signed.
`amount_basis` is `gross`, `net`, or `unknown`. Unknown bases never become zero.

### Announcements

```json
{
  "id": "ann-1", "revision": 1, "status": "announced",
  "source": {"kind": "manual", "reference": "Reviewed issuer notice", "as_of": "2026-01-01"},
  "scope": {"holding_id": "holding-1"}, "income_type": "dividend",
  "payment_date": "2026-02-01", "ex_date": "2026-01-15", "record_date": "2026-01-16",
  "money": {"amount": 50, "currency": "USD"}, "amount_basis": "gross", "amount_kind": "total"
}
```

All shown fields except `ex_date` and `record_date` are required. `income_type` is
`dividend` or `interest`. Preserve source ex, record and payment dates explicitly;
no calendar ordering or eligibility rules are inferred. `status` is `announced` or
`cancelled`. Repeated identical `(id, revision)` rows deduplicate; conflicting rows
at the same revision fail. The largest positive integer revision wins, regardless
of input order. A cancellation is a full replacement row, with the same required
fields. It produces no expected entitlement, and historical links to it are
excluded from comparisons with a diagnostic. Actual received income is unaffected.

`amount_kind: "total"` means the source declares a total for the exact scope.
`amount_kind: "per_unit"` multiplies the amount only when an explicit
`entitlement_quantity` and `entitlement_source` are both present. Quantity must be
nonnegative and is valid only for `per_unit`. The evidence should identify the
historical entitlement and source record date. Without it the expected amount is
unavailable. Present-day quantity and market value are never substituted.

### Scenario estimates

Each estimate requires `id`, `scenario`, `assumptions` (nonempty text), `source`,
`scope`, `income_type`, `payment_date`, `money`, and `amount_basis`.
Estimates describe a total amount for their scope. They have no revision or
entitlement mechanism. Duplicate identical IDs deduplicate; conflicting IDs fail.
They appear only in `estimates`, never in matching or yield calculations.

### Reviewed payment links

```json
{
  "announcement_id": "ann-1", "activity_id": "payment-1",
  "source": {"kind": "manual", "reference": "Reviewed payment allocation", "as_of": "2026-02-02"}
}
```

These three fields are required. A link is a reviewed whole-payment assignment;
v1 does not split or allocate an activity among announcements. Dates and amount
resemblance never create links. Unknown IDs fail. Original activity IDs follow
all correction successors before any filtering. Repeated assignments to the same
effective activity/announcement deduplicate, even when both an original and its
replacement are linked. Assignments of one effective activity to different
announcements fail. Links to pending or cancelled effective activities are ignored
with diagnostics. Links to buys or reinvestment buy legs fail; only posted declared
dividend/interest events can match. Scope, native currency, event type and requested
gross/net availability must agree. Gross can be derived from net (or vice versa)
only under the received engine's explicit withholding and fee rules.

Links are checked against the entire effective history. Payments outside selected
start/end dates are excluded from the selected comparison and explained in the row
reason and diagnostics. A payment may legitimately have a different source date
than an announcement; the reviewed link provides that allocation.

### Declared cost bases

```json
{
  "id": "cost-1", "scope": {"holding_id": "holding-1"},
  "source": {"kind": "manual", "reference": "Reviewed constant acquisition cost and complete broker statement", "as_of": "2026-12-31"},
  "method": "declared_constant_cost", "period": {"start": "2026-01-01", "end": "2026-12-31"},
  "money": {"amount": 1000, "currency": "USD"}, "amount_basis": "gross",
  "coverage": "complete", "income_source_system": "sample-broker"
}
```

All fields except `income_source_system` are required; an absent income source
makes yield unavailable. `coverage` is `complete`, `partial`, or `unknown`. The
source evidence must explicitly support constant cost and received-income
coverage for the stated source, scope and inclusive period. `complete` is a user
or provider assertion, not a conclusion from seeing some payments. The calculator
does not prove the truth of supplied evidence. Identical cost IDs deduplicate;
conflicting IDs fail. Period start must be on or before end.

The supported method is deliberately narrow:

`ratio = sum(actual received gross-or-net dividend and interest during period) / declared constant native-currency cost`

It is a period ratio, never automatically annualized. A result of `0.05` is 5%.
It is not total return, a forward yield, or a denominator reconstructed from tax
lots. No current market value or FX conversion enters either side. Gross and net
use the received engine's source amounts and explicit charge rules. There is no
extra deduction of unrelated tax events.

Yield is unavailable with a reason when cost, coverage, source, attribution,
requested income basis, or currency is unknown or incompatible. Known matching
income from a different source makes a scoped result unavailable rather than
silently dropping it. Missing dimensions that could belong to the scope also make
it unavailable. A source scope and `income_source_system` must agree. A complete
source declaration with no candidate payments can yield zero.

Posted buys, sells, transfers, splits, amortization, corporate actions, and explicit
cost-basis adjustments during the period make constant-cost yield unavailable.
Unclassified generic income also prevents a complete numerator. Corrections are
applied before these checks. v1 has no changing-cost denominator method. A selected
date window must include the entire declared cost period; a shorter window yields
unavailable instead of relabeling the basis or annualizing a partial numerator.

## Python result contract

```python
build_income_planning_report(portfolio, received_report, plan, *, start=None, end=None)
```

`received_report` must contain the canonical received events for the same
portfolio and requested dates. The function verifies these events with the received
engine, suppressing the embedded plan while doing so. It never mutates inputs and
returns independent JSON-safe objects. Invalid contracts raise `ValueError`.

The result contains `version: 1`, `start`, `end`, and these lists:

| List | Row contract |
| --- | --- |
| `announced` | Latest selected input row, plus `currency`, `expected_amount` (number or null), `reason` (text or null). Cancelled revisions remain visible with null expected amount. |
| `estimates` | Selected input row, plus `currency` and `estimated_amount`. Always visibly separate from actual income. |
| `reconciliation` | `announcement_id`, `scope`, `income_type`, `payment_date`, `currency`, `amount_basis`, `expected_amount`, `received_amount`, `known_received_subtotal`, `activity_ids`, `status`, `reason`. |
| `yield_on_cost` | `id`, `scope`, `source`, `method`, `period`, `currency`, `amount_basis`, `coverage`, `income_source_system` (text or null), `cost_basis`, `received_amount`, `activity_ids`, `ratio`, `status`, `reason`. |
| `diagnostics` | `id` (announcement ID or null) and `message` (source-aware explanatory text). |

Reconciliation `activity_ids` are unique effective IDs, sorted lexically. Status
is `matched`, `partial`, `overpaid`, `unlinked`, `unavailable`, or `cancelled`.
Partial/overpaid compares only explicitly linked received amounts against the
explicit expectation. It does not assert complete payment coverage. With no
selected payment, `received_amount` is null and `known_received_subtotal` is zero;
`unlinked` never alleges a late or missing payment. Yield status is `available` or
`unavailable`; an unavailable result has null `ratio` and `received_amount` plus a
reason. Every yield row retains its declared `coverage` and `income_source_system`
(null when absent), including unavailable results, so exported results preserve the
evidence behind the decision. Lists are deterministic by ID, diagnostics by
announcement/activity link.

Inclusive date filters use each activity's source-local calendar day, preserving
the received engine's explicit timestamp offset. Announcements and estimates use
their declared payment date. Filtering never creates historical holdings or
changes the period on a declared cost row.

The synthetic [sample plan](../../tests/fixtures/income_plan.json) matches
`ann-1`, `payment-1`, `holding-1` and source `sample-broker`: a received gross
payment of USD 50 against declared constant cost USD 1000 yields `0.05`. Its
USD 999 scenario never enters that numerator.
