# Reconcile profit, currency effects and revised splits

Use this workflow with local reviewed evidence. The examples are synthetic and
need no account, provider connection or paid key. Install the project dependencies
first, then run commands from the repository root.

## Replay the multicurrency example

```bash
uv run rikdom performance \
  --data-dir out/profit-fx-workspace \
  --portfolio data-sample/profit-attribution-fx/portfolio.json \
  --snapshots data-sample/profit-attribution-fx/snapshots.jsonl \
  --historical-fx data-sample/profit-attribution-fx/historical-fx.json \
  --profit-basis data-sample/profit-attribution-fx/basis.json
```

The period residual is BRL 550. The separately computed components are realized
price result 120, realized currency effect 80, unrealized price change 110,
unrealized currency change 80 and cash currency effect 160. Their sum is 550;
`reconciliation_difference_base` is zero. Acquisition, event and bookend exchange
rates and source vintages are retained in `fx_evidence`. The native USD cash
balance reconciles from 50 to 110 after the USD 60 sale.

For an offline report using exactly those calculation inputs:

```bash
uv run rikdom viz \
  --data-dir out/profit-fx-workspace \
  --portfolio data-sample/profit-attribution-fx/portfolio.json \
  --snapshots data-sample/profit-attribution-fx/snapshots.jsonl \
  --historical-fx data-sample/profit-attribution-fx/historical-fx.json \
  --profit-basis data-sample/profit-attribution-fx/basis.json \
  --out out/profit-fx/dashboard.html
```

The detailed price/currency table explains the realized and unrealized totals.
Cash currency effects and explicit currency-conversion results are separate
period components. The report formats the Python results and performs no
financial calculation in the browser. Legacy line-item `fx_ref` warnings can
still appear for the synthetic canonical holdings: the v2 calculation uses its
explicit dated market-series evidence, separately from current holding trust.

If an acquisition rate or reviewed historical position is missing, inspect
`profit_attribution.decomposition.status` and diagnostics. A valid residual bridge
can remain complete while the detailed components are unavailable. This does not
establish a complete cost basis or a tax liability.

## Replace a reviewed split revision

Start with a scratch copy so the tracked example stays unchanged:

```bash
cp data-sample/market-events/portfolio.json /tmp/rikdom-split-portfolio.json

uv run rikdom market-events apply \
  --input data-sample/market-events/us.json \
  --event synthetic-us-split --as-of 2026-02-01T00:00:00Z \
  --portfolio /tmp/rikdom-split-portfolio.json \
  --review data-sample/market-events/split-review.json --write

uv run rikdom market-events preview \
  --input data-sample/market-events/split-revisions.json \
  --event synthetic-us-split --as-of 2026-02-01T00:00:00Z \
  --portfolio /tmp/rikdom-split-portfolio.json \
  --review data-sample/market-events/split-revision-review.json

uv run rikdom market-events apply \
  --input data-sample/market-events/split-revisions.json \
  --event synthetic-us-split --as-of 2026-02-01T00:00:00Z \
  --portfolio /tmp/rikdom-split-portfolio.json \
  --review data-sample/market-events/split-revision-review.json --write
```

The 3:1 revision is a full replacement for the earlier 2:1 event. It appends an
immutable correction link; both original and revised source evidence stay in the
stored ledger. Effective calculations use only the latest event. Repeating either
already-applied review produces a no-op and does not rewrite the file.

The review must identify the same account, holding, original pre-split quantity
and descendant source revision. Version 1.1 records the effective and review dates.
The workflow rejects adjusted quantities, changed source history, missing lot
evidence, dependent tax lots and unsupported later basis-changing actions. Those
cases require a separate reviewed position/lot migration before applying a
revision. Current imported holdings and quoted prices remain source observations;
the ledger correction does not invent a replacement position or adjust prices.

## Reconcile a revised split with foreign FIFO

The integration test `tests.test_profit_fx_workflow` exercises a foreign holding
with ten units, a 2:1 event corrected to 3:1, then a sale of twelve units. FIFO ends
with eighteen units and preserves remaining costs of USD 60 and historical BRL 240.
The period residual of BRL 776 is independently explained by realized price 120,
realized FX 80, unrealized price change 236, unrealized FX change 80 and cash FX 260.
The CLI and offline report receive identical component and provenance objects.

A revision reviewed after the basis retrieval cutoff cannot establish what was
known earlier. The detailed attribution becomes unavailable while the current
residual remains separately disclosed. Recalculate with an intentionally updated
reviewed basis and cutoff to use that later evidence.

See the [profit basis reference](../reference/profit-attribution.md) and
[market-event revision contract](../reference/market-events.md).
