# Profit attribution and period reconciliation

`rikdom.profit_attribution.compute_profit_attribution(portfolio, performance,
basis=None, historical_fx=None)` calculates read-only evidence. `basis` and
`historical_fx` are keyword-only. It does not fetch data or change the ledger.

The always-present `bridge` object reconciles these reporting-currency amounts:

```text
opening_value_base + net_external_cashflow_base + investment_result_base
    = closing_value_base
```

`investment_result_base` is the **period residual**: closing value minus opening
value minus signed net external flows. It already includes income, charges,
price changes and currency effects reflected in portfolio value. Adding dividends
to this residual would count them twice. It is neither lifetime profit nor a
realized tax gain. This identity does not independently verify the market values
in the supplied `PerformanceResult` or establish that an imported ledger contains
all real-world transactions.

A complete bridge requires increasing timezone-aware bookend instants,
nonnegative finite values, verified reporting currencies, and complete valid
external-flow conversion. The effective corrected/deduplicated ledger must agree
with the supplied performance net flow and flow count. Missing dates, malformed
cash, unavailable or undated foreign FX, and unresolved transfer identity make
all bridge amounts null. Snapshot warnings that indicate missing or mismatching
currency/value evidence also block the bridge. A TWR fallback caused only by
missing before/after flow valuations does not block this monetary identity.

`historical_fx` supplies directional dated conversion **only for external flows**.
Each flow retains its native amount/currency, signed converted amount, activity
identity and lookup evidence including source, retrieval cutoff, revisions and
coverage. It does not establish historical portfolio valuation or foreign tax-lot
cost completeness.

## Availability and provenance

The result has `contract_version: "1.0"`, `scope: "portfolio"`,
`return_basis: "period"`, reporting currency and bookend timestamps.
Top-level `status` describes **only the bridge**, as declared by
`status_scope: "bridge"`. Inspect `decomposition.status` separately.

- `status: "complete"` and `decomposition.status: "unavailable"` means the period
  residual is available but realized/unrealized components are unknown.
- `decomposition.status: "complete"` means the supported reviewed FIFO evidence
  reconciles positions, cash and the residual.
- `status: "unavailable"` means even the residual cannot be asserted.

Every unavailable component is null; no partial subtotal is returned as a full
profit amount. `diagnostics` states why evidence was rejected. Computed result
fields do not consume broker-reported profit or current `portfolio.tax_lots`.
`decomposition.basis_evidence` retains a detached copy of accepted reviewed
inputs. Activity rows distinguish `reported_amount_native`, nullable
`reported_fees_native`/`reported_taxes_native`, applied charges, computed net cash,
and FIFO lots consumed. No reported standalone profit is treated as computed.

Published basis, raw history and FX provenance are detached strict JSON evidence:
objects with string keys, arrays, strings, booleans, null and numbers within the
supported finite range. Nonfinite values in superseded rows or arbitrary metadata
are rejected too. Python API inputs containing tuples, cycles, nonstring keys or
arbitrary objects are rejected instead of coerced. Invalid basis/history evidence
leaves the entire decomposition unavailable with null components and evidence;
no partial provenance or computed component totals are published.

## Reviewed FIFO evidence version 1.0

`load_profit_basis(path)` reads a JSON object and rejects duplicate keys,
NaN/Infinity and overflowing floating-point literals. Semantic errors are
reported by `compute_profit_attribution` as unavailable decomposition. All
objects below require exactly the shown keys. Numeric values are finite JSON
numbers; quantities and reviewed costs/values/cash are nonnegative. Account and
holding IDs are explicit and nonempty. All timestamps have a timezone.

A complete synthetic example is checked in at
[`data-sample/profit-attribution/basis.json`](../../data-sample/profit-attribution/basis.json),
with matching
[`portfolio.json`](../../data-sample/profit-attribution/portfolio.json) and
[`snapshots.jsonl`](../../data-sample/profit-attribution/snapshots.jsonl).
The numbers are invented and the files require no paid source or network.

```json
{
  "contract_version": "1.0",
  "scope": "portfolio",
  "base_currency": "BRL",
  "period_start": "2026-01-01T00:00:00Z",
  "period_end": "2026-02-01T00:00:00Z",
  "method": "fifo",
  "price_adjustment": "unadjusted",
  "cost_convention": "buy_costs_capitalized_sell_costs_deducted",
  "review": {
    "status": "reviewed",
    "source": "synthetic reviewed statement",
    "reviewed_at": "2026-02-02T00:00:00Z",
    "retrieved_before": "2026-02-02T00:00:00Z"
  },
  "history": {
    "status": "complete",
    "from": "2026-01-01T00:00:00Z",
    "through": "2026-02-01T00:00:00Z",
    "missing_periods": []
  },
  "opening_cash_base": 80,
  "closing_cash_base": 214,
  "opening_lots": [{
    "id": "old",
    "account_id": "a",
    "holding_id": "h",
    "currency": "BRL",
    "acquired_at": "2025-01-01T00:00:00Z",
    "quantity": 10,
    "total_cost_native": 100
  }],
  "opening_positions": [{
    "account_id": "a",
    "holding_id": "h",
    "currency": "BRL",
    "quantity": 10,
    "market_value_native": 120
  }],
  "closing_positions": [{
    "account_id": "a",
    "holding_id": "h",
    "currency": "BRL",
    "quantity": 3,
    "market_value_native": 66
  }]
}
```

The reviewer asserts that `opening_lots` are **all remaining lots at opening**,
including historical acquisition costs and already-capitalized acquisition
charges, and that opening/closing positions and cash describe the whole
portfolio. Empty lists explicitly assert no positions; absent lists are invalid.
FIFO is calculated independently by `(account_id, holding_id)`; one account's
inventory cannot cover another's sale. Multiple lots at the same acquisition
instant or multiple trades for one position at the same instant are rejected
because this version has no ordering convention for them.

`history` must assert complete coverage from the exact opening instant through
the exact closing instant, without missing periods. The period equals the
performance bookends. The reviewer must review no earlier than the period end,
and the retrieval cutoff must cover the period and precede or equal review.
`review.source` identifies the reviewed evidence; this declaration records user
review, not independent attestation by Rikdom.

The cutoff is enforced against every supplied `ingested_at` and `created_at`
on raw period events and their complete connected correction lineage. This
includes superseded events, cancellations and corrections whose effective dates
move outside the period. Malformed or timezone-naive knowledge timestamps and
any known timestamp after `retrieved_before` make the decomposition unavailable.
The valid residual bridge can remain available because it describes the supplied
latest ledger rather than an as-known historical snapshot.

This version does not reconstruct an earlier ledger as known at the cutoff.
Unrelated future events outside the period and its correction lineage do not
block the period decomposition. Absent ingestion/creation timestamps are not
inferred; their temporal coverage remains part of the explicit reviewer
assertion. A completed decomposition retains detached raw rows, including
correction links and source/ingestion fields, in `history_evidence.activities`,
along with the cutoff and scope. This evidence records exactly which supplied
lineage passed the conservative temporal check.

All FIFO position values, transaction cash and costs must be in the reporting
currency. This makes `*_native` and `*_base` amounts identical for the supported
breakdown. Foreign positions, foreign trading/fee/tax currencies and FX gain
allocation are unavailable even if external-flow FX is complete. No undated FX
rate is used to manufacture reporting-currency historical costs.

## FIFO and charge treatment

Only posted effective events are used. Superseded/cancelled events are excluded.
Identical activity IDs or idempotency-key imports are counted once; conflicts
make the bridge unavailable. If deduplicated external flows disagree with the
supplied performance calculation, the bridge is unavailable instead of silently
changing the supplied result. No canonical inputs are mutated.

The supported period is after opening through closing for FIFO. Events exactly
at opening are rejected because the evidence does not specify whether they
are already included in the opening position. External-flow extraction retains
the performance engine's inclusive boundary convention.

- A `buy` requires positive quantity; amount plus embedded fees and withholding
  becomes the new lot's cost and cash outflow.
- A `sell` requires positive quantity; amount minus embedded fees/withholding is
  net proceeds. Realized gain is proceeds minus historical FIFO cost removed.
- `dividend`, `interest` and `income` use `income_amount_basis` semantics. Gross
  amounts deduct embedded charges; a known net receipt is retained once.
  Unknown gross/net basis blocks decomposition.
- Standalone `fee` and `tax_withheld` events reduce cash and their respective
  result components. Embedded trade charges remain in FIFO cost/proceeds;
  embedded income charges remain in net income. They are not deducted again.
- Absent embedded charges apply zero under the reviewed complete-history and
  explicit cost-convention assertion; their reported evidence stays null.
- Contributions/withdrawals with no holding reference, quantity or embedded
  costs can reconcile cash. In-kind flows, transfers, splits, mergers,
  amortization, reimbursement, FX conversion, other movements, and any
  `corporate_action` or `cost_basis_adjustment` field block decomposition.
  Signed cost-basis adjustments require unsupported basis-carryover accounting,
  including when attached to an otherwise supported sale or income event.
  No unsupported event is ignored
  merely because it reports zero money.

Opening lot quantities must match opening positions. Reconstructed closing
quantities must match closing positions. Cash movements must reconcile opening
to closing cash, and cash plus positions must match both performance values.
The fixed absolute reconciliation tolerance is 0.00000001 reporting-currency
units; quantities reconcile exactly. Money uses decimal arithmetic internally
and finite floats in JSON output. Fractional FIFO allocations can round at the
decimal context precision; the same tolerance applies to the final bridge.

The completed decomposition exposes:

```text
realized_gain_base
+ (closing_unrealized_gain_base - opening_unrealized_gain_base)
+ net_income_base - standalone_fees_base - standalone_taxes_base
= explained_result_base
= bridge.investment_result_base
```

The change in unrealized gain is the period component; closing unrealized gain
alone includes earlier periods. Realized gains recognized on period sales use
historical acquisition costs, including lots acquired before the period. This
is an accounting decomposition, not a jurisdiction-specific tax calculation.

In the synthetic example, opening cash 80 plus positions 120 equals 200.
Buying five units for 75 plus 5 fees creates an 80-cost lot. Selling twelve for
216 less 6 fees and 2 tax gives proceeds of 208. FIFO removes cost 132 (all ten
old units at cost 100 plus two new units at cost 32), realizing 76. Three units
remain with cost 48 and market value 66, so closing unrealized gain is 18;
opening unrealized gain was 20. Net income is 10 and separate fee/tax are 3/1.
Thus `76 - 2 + 10 - 3 - 1 = 80`, and `200 + 0 + 80 = 280`.

No since-inception total, after-tax liquidation estimate, short positions,
margin/debt accounting, corporate-action basis carryover, or foreign FIFO
profit is inferred. Unsupported evidence preserves the valid residual and
leaves the decomposition unavailable.
