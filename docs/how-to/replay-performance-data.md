# Reproduce historical valuations and profit offline

Use this workflow after installing the project dependencies. Inputs are local
files; the commands need no account, API key, or network. The examples contain
invented values and establish calculation mechanics only.

## Replay explicit historical positions

Prepare the full positions and cash balances at each requested instant using the
[historical valuation contract](../reference/historical-valuation.md). Give each
position its exact namespaced instrument identity and price series. Supply native
quantities at that date, unadjusted prices, directional FX, freshness limits and
an optional retrieval cutoff. Current holdings cannot supply historical units.

Run the tracked example against a portfolio whose reporting currency is BRL:

```bash
uv run rikdom performance \
  --portfolio data-sample/historical-valuation-replay/portfolio.json \
  --historical-valuations data-sample/historical-valuation-replay/replay.json \
  --historical-fx data-sample/historical-valuation-replay/historical-fx.json \
  --flow-valuations data-sample/historical-valuation-replay/flow-valuations.json
```

The replay replaces recorded performance snapshots for this calculation. Its
opening and closing values are BRL 135 and BRL 254. The supplied USD 12
contribution converts to BRL 72, leaving BRL 47 investment result and a selected
linked TWR of 34.814815%. The internal purchase adds no external cashflow.
Valuations alone do not establish
complete transaction history: returns also depend on the supplied activity ledger.
`valuation_replay` retains the per-position price/FX, source, revisions and
coverage evidence. `valuation_status` is `complete` only if every requested
valuation is available. A missing or stale required input leaves return measures
unavailable; the command does not substitute today's holdings or recorded totals.

## Reconcile the period and inspect FIFO gains

Supply reviewed opening lots, opening/closing positions and cash, and a complete
period history assertion using the [profit basis contract](../reference/profit-attribution.md):

```bash
uv run rikdom performance \
  --portfolio data-sample/profit-attribution/portfolio.json \
  --snapshots data-sample/profit-attribution/snapshots.jsonl \
  --profit-basis data-sample/profit-attribution/basis.json
```

The synthetic result is `200 + 0 + 80 = 280`: opening value, net external
contributions, investment result, and closing value. FIFO explains the BRL 80 as
BRL 76 realized gain, BRL -2 change in unrealized gain, BRL 10 net income, less
BRL 3 separate fees and BRL 1 separate taxes. Net receipts are not reduced by their
reported embedded charges again. Income already reflected in NAV is not added
to the residual a second time.

Inspect `profit_attribution.bridge` separately from `decomposition`. A bridge is
arithmetic on supplied bookends and ledger, not independent proof of complete
real-world history. Missing reviewed basis leaves gain decomposition unavailable.
The initial FIFO contract supports reporting-currency long-only plain positions;
foreign lots, corporate actions and unsupported movements remain unavailable.

## Put the same calculations in an offline report

Pass the same calculation files and dates to `viz`:

```bash
uv run rikdom viz \
  --portfolio data-sample/profit-attribution/portfolio.json \
  --snapshots data-sample/profit-attribution/snapshots.jsonl \
  --profit-basis data-sample/profit-attribution/basis.json \
  --out out/profit-example/dashboard.html
```

For the tracked multi-currency linked-TWR example:

```bash
uv run rikdom viz \
  --portfolio data-sample/performance-fx/portfolio.json \
  --snapshots data-sample/performance-fx/snapshots.jsonl \
  --historical-fx data-sample/performance-fx/historical-fx.json \
  --flow-valuations data-sample/performance-fx/flow-valuations.json \
  --out out/linked-example/dashboard.html
```

The selected TWR is 21%, with the same result contract as `performance`.
`--policy` and `--benchmarks-dir` enable the same benchmark comparisons in both
commands. Reports disclose selected dates, return method, annualization,
fees/taxes treatment, quality warnings and unavailable gain components. Full
and fallback HTML use the same offline panel. Keep the entire output directory.

The report's current holdings valuation remains separate from historical replay.
`--include-current` cannot be combined with `--historical-valuations`. Browser
date filters that narrow the precomputed return window make its performance
unavailable; they do not recalculate a new return in JavaScript. Unsupported
account/type/currency scopes remain explicit. Re-render with `--since` and
`--until` to calculate another portfolio period.

## Replay normalized data through a local provider

Save a request containing an explicit cache path and lookup parameters, following
[the enrichment reference](../reference/enrichment.md), then run:

```bash
uv run rikdom enrichment --plugin local-market-series --request request.json
uv run rikdom plugin init my-local-provider --type enrichment --dest plugins
```

The enrichment command prints validated MarketSeries and host-derived lookups.
Inspect each lookup status before using it. BR/US/Japan fixtures demonstrate
neutral contracts, not maintained live market coverage or exchange calendars.
To feed an enrichment response into historical valuation, save only its
`market_series` document as the local file referenced by your valuation config;
the response envelope itself is not a MarketSeries file.
