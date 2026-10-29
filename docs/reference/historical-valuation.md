# Historical valuation replay

`replay_historical_valuations(path: str | Path, *, base_currency: str) -> dict[str, Any]`
values explicitly dated historical positions using a local [MarketSeries 1.0
file](market-series.md) and [directional historical FX](historical-fx.md).
It reads no current holdings and performs no network calls or writes.

## Input contract 1.0

The configuration contains exactly these required fields:

```json
{
  "contract_version": "1.0",
  "market_series_file": "market.json",
  "price_max_age_seconds": 86400,
  "fx_max_age_seconds": 86400,
  "retrieved_before": null,
  "series_by_currency": {"USD": "usd-brl"},
  "snapshots": [
    {
      "as_of": "2026-01-02T00:00:00Z",
      "source": "reviewed full position statement",
      "positions_complete": true,
      "positions": [
        {
          "id": "stock",
          "kind": "security",
          "instrument": {"namespace": "synthetic", "id": "US-ONE", "currency": "USD"},
          "quantity": 2,
          "price_series_id": "stock-us"
        },
        {"id": "cash-brl", "kind": "cash", "currency": "BRL", "amount": 20},
        {"id": "cash-usd", "kind": "cash", "currency": "USD", "amount": 3}
      ]
    }
  ]
}
```

| Field | Contract |
| --- | --- |
| `market_series_file` | Nonblank local path. Relative paths use the configuration directory. Absolute paths are accepted. |
| `price_max_age_seconds`, `fx_max_age_seconds` | Separate finite nonnegative numeric age limits. Effective quote age is inclusive at the limit. Booleans are invalid. |
| `retrieved_before` | Inclusive UTC quote-retrieval cutoff, or `null` to use all revisions in the file. Applies to both prices and FX. |
| `series_by_currency` | Explicit native-currency-to-FX-series mapping. Rates multiply native amounts into `base_currency`. No inverse or cross-rate is inferred. |
| `snapshots` | Nonempty array of full position evidence. Each distinct instant contains exactly `as_of`, `source`, `positions_complete`, and `positions`. |
| `as_of` | Explicit UTC timestamp ending in `Z` or `+00:00`, with optional fractional seconds. Duplicate instants are rejected. |
| `source` | Nonblank position-evidence source, without surrounding whitespace. |
| `positions_complete` | Boolean assertion about the entire portfolio at that instant. `false` produces unavailable valuation evidence. Empty `positions` with `true` explicitly asserts a zero-value portfolio. |
| `positions` | Array of security or cash rows. Position IDs are nonblank and unique within each snapshot. Quantities and cash amounts are finite nonnegative numbers. |

Security rows contain exactly `id`, `kind`, `instrument`, `quantity`, and
`price_series_id`. Their `instrument` contains exactly `namespace`, `id`, and
`currency`. All three fields must match the selected price series identity;
its kind must be `price`. Only `adjustment: unadjusted` is supported.
`split_adjusted` and `total_return_adjusted` prices cannot value these quantities.
No split, merger, trade, cost-basis, or current-position reconstruction occurs.
Historical snapshots must already reflect any position changes.

Cash rows contain exactly `id`, `kind`, `currency`, and `amount`. They require
no price. Cash in the reporting currency uses identity FX of 1. Foreign cash
requires the same explicit directional FX evidence as a security. Zero-quantity
security rows still require valid price and FX evidence; they are never skipped.

Every object has exactly its declared fields. Unknown fields, missing fields,
duplicate JSON keys, duplicate position IDs, invalid currencies/timestamps,
nonfinite JSON constants, booleans in numeric fields, ambiguous MarketSeries
revisions, and unsupported versions raise `ValueError`. File access errors
propagate as `OSError`. No malformed row is silently discarded.

`base_currency` is a required caller argument with three uppercase letters;
it is not a configuration field. Currency syntax does not verify a live registry.
The quote cutoff controls market evidence only: the supplied position statements
are caller assertions, not a reconstruction of what positions were known at a
past retrieval time.

## Output contract 1.0

| Field | Meaning |
| --- | --- |
| `contract_version` | `"1.0"`. |
| `base_currency` | Reporting currency requested by the caller. |
| `status` | `complete` only when every position of every requested snapshot can be valued and every position list is asserted complete; otherwise `unavailable`. |
| `snapshots` | Chronologically sorted, schema-compatible Rikdom snapshots when the whole replay is complete. Always `[]` if any requested snapshot is unavailable. |
| `valuations` | Evidence for every requested snapshot, including failed dates and all positions. Each row contains `as_of`, `source`, `positions_complete`, `status`, `portfolio_value_base`, `positions`, and `diagnostics`. |
| `diagnostics` | Per-date unavailability reasons. Empty for complete replay. |

A usable snapshot has this shape:

```json
{
  "timestamp": "2026-01-02T00:00:00Z",
  "base_currency": "BRL",
  "totals": {"portfolio_value_base": 135.0, "by_asset_class": {}},
  "metadata": {
    "historical_valuation": {
      "source": "reviewed full position statement",
      "convention": "unadjusted_price"
    }
  }
}
```

No asset-class, account, or policy-bucket attribution is inferred. Full
valuation evidence accompanies the snapshots separately.

Each position result contains the original `position`, `status`
(`complete`/`unavailable`), primary `reason`, all `diagnostics`, `native_value`,
`base_value`, `price`, and `fx`. Cash has `price: null`. Security `price`
retains the complete MarketSeries lookup, including requested instant,
retrieval cutoff, age limit, status/reason, declared identity/coverage/license,
selected observation with source/effective/retrieval dates, and superseded
revisions. `fx` retains the HistoricalFx evidence, including requested pair,
rate or `null`, and the same lookup provenance for mapped currencies.

`native_value` is quantity times unadjusted price, or declared cash.
`base_value` is native value times the selected rate. Either is `null` when
its evidence is unavailable or its calculation overflows. A valid native
value can remain visible when its FX conversion is unavailable.

Missing/stale/future quotes, wrong price identity, adjusted prices, wrong FX
pair, and numeric overflow produce explicit unavailable evidence. Failed
snapshot totals are `null`; available positions remain visible without
forming a partial portfolio total. A single failed date suppresses the entire
usable `snapshots` list so bookend selection cannot silently skip that date.
`reason` keeps the first failure; `diagnostics` retains all failures, including
both price and FX defects on the same position. The raw lookup may be
`available` while the position is unavailable because identity or adjustment
checks rejected that quote.

Results are detached and deterministic for unchanged inputs. There is no
current clock, implicit fallback, rounding policy, or canonical portfolio/ledger
mutation. Numbers use finite Python floating-point arithmetic.

## Offline sample

The synthetic, freely reusable
[replay config](../../data-sample/historical-valuation-replay/replay.json) and
[market series](../../data-sample/historical-valuation-replay/market.json)
contain no personal holdings or live-market coverage claim. Sample observation
license metadata declares CC0 and uses an explicitly nonresolving example URI.

```python
from rikdom.historical_valuation import replay_historical_valuations

result = replay_historical_valuations(
    "data-sample/historical-valuation-replay/replay.json", base_currency="BRL"
)
assert result["status"] == "complete"
assert [s["totals"]["portfolio_value_base"] for s in result["snapshots"]] == [135, 254]
```

Opening: `2 × 10 USD × 5 BRL/USD + 20 BRL + 3 USD × 5 = 135 BRL`.
Closing: `3 × 12 USD × 6 BRL/USD + 20 BRL + 3 USD × 6 = 254 BRL`.
The changed quantity is independently supplied position evidence. These are
portfolio valuations, not an investment return or profit calculation; external
flows and complete cost history are separate evidence requirements.
