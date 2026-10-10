# FII history conventions

Schema 1.6.0 extends the existing `activities` and `tax_lots` ledgers. These
conventions also support Fiagro and other listed instruments. Existing
portfolios remain readable; the additive migration preserves their contents.

## Cash events and dates

- `buy`: `money` is purchase consideration; `fees` contains allocated costs.
- `sell`: `money` is gross proceeds; fees and reported withholding reduce cash.
- `dividend`: gross reported distributions, with `withholding_tax` when known.
- `amortization`: cash returned to the investor. A reported signed basis delta
  can be recorded separately in `cost_basis_adjustment`.
- `fee` and `tax_withheld`: separate charges. Do not duplicate a charge that is
  already attached to another activity.

`trade_at` identifies execution; `settled_at` identifies the reported cash
settlement date. The instrument calculator uses `settled_at`, falling back to
`effective_at`. For date-only source records, anchor timestamps consistently
in the source timezone and preserve `metadata.date_precision: "day"`. Record
unresolved cash dates in metadata and keep the history partial.

Preserve a source reference down to document/page or statement row. Stable IDs
and `idempotency_key` should identify economic events across repeated imports.
Annual reports and monthly statements can show the same receipt. Annual income
totals are reconciliation checks, not invented dated cashflows.

## Corporate actions and cost basis

`corporate_action` contains `kind`, `legs`, and an optional positive
`exchange_ratio`. Kinds are `split`, `reverse_split`, `ticker_change`, `merger`,
`subscription_conversion` and `rights_issue`.

Each leg identifies a `holding_id` and signed `quantity_delta`, with optional
signed `cost_basis_delta` and `tax_lot_ids`. For a 1-to-10 split of 100 units,
the quantity delta is +900; total basis is unchanged. A receipt conversion
typically records a negative receipt leg and a positive principal-unit leg.
Source documents must establish the ratio, date and basis treatment.

Use an appropriate event type such as `split`, `merger` or `other` with a
subtype. A documented noncash corporate action contributes no cash return.
Separate actual subscription payments or cash components into auditable cash
events. Unhandled monetary components block complete instrument returns.

Keep a stable holding ID through a simple ticker change. Explicit historical
ticker aliases can be retained in `metadata.instrument_aliases`. Direct
`holding_id` references take precedence over ticker matching. A multi-instrument
merger requires a reconciled economic lineage; its basis transfer alone cannot
establish the successor's original invested cash.

`tax_lots` records acquisition dates, quantities, cost basis including allocated
fees, and acquisition/disposal activity links. Imported lots are assertions;
Rikdom does not manufacture remaining lots from incomplete transactions or
select a Brazilian tax-basis method automatically.

## History coverage

```json
{
  "extensions": {
    "rikdom_instrument_history": {
      "status": "partial",
      "from": "2022-03-02",
      "through": "2026-09-30",
      "missing_periods": [
        {"from": "2026-08-01", "through": "2026-08-31", "kind": "transactions"}
      ],
      "notes": ["Receipt conversions and settlement dates await reconciliation"]
    }
  }
}
```

`status` is `complete`, `partial` or `unknown`. Complete coverage requires
`from` and `through`. Missing-period kinds distinguish `transactions`,
`distributions`, `corporate_actions` and `all`. Missing statements and missing
events are different: another document can recover a month's distributions
while purchase/sale history remains unresolved.

## Normalized imports

```bash
uv run rikdom import-statement --data-dir data \
  --plugin normalized-statement-json --input recovered-statement.json --dry-run
```

The payload follows `schema/plugin-statement.schema.json`, with `provider`,
`generated_at` and at least one of `holdings`, `activities` or `tax_lots`.
Use `--write` after reconciling the displayed changes. The importer validates
dates and structure, stamps provenance, merges lots by stable identity and
rejects conflicting identities or unresolved references.

## Quotes and comparison assumptions

Keep the current dated value in `holding.market_value` and `holding.as_of`.
Historical benchmark levels use `data/benchmarks/<id>.jsonl` rows with `as_of`,
`level` and `currency`. A total-return index can be a benchmark; it does not
identify the price and tax treatment of an actual Tesouro or CDB contract.

Additional reproducible product inputs can be stored under
`portfolio.extensions.rikdom_comparison_inputs`, keyed by scenario ID. Preserve:

- product identity, issuer and maturity;
- historical purchase and resale quotes, quote timestamps and source references;
- CDB contracted index, percentage/spread, day-count and capitalization rules;
- the same dated contributions and the chosen distribution reinvestment or
  withdrawal rule;
- fees, tax assumptions, applicability dates and any loss-compensation state;
- valuation date and whether quoted values are gross or net.

This extension is an input-storage convention. The instrument calculator does
not yet simulate product-specific Tesouro/CDB contracts or infer their net tax
results. Record estimates and missing inputs explicitly instead of asserting
a net benchmark return.

The instrument/portfolio cashflow boundary follows the approach documented in
the [Portfolio Performance money-weighted return manual](https://help.portfolio-performance.info/en/concepts/performance/money-weighted/).
