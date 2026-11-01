# Reviewed historical reference workflow

These invented inputs are dedicated under CC0-1.0. They demonstrate mechanics,
not investment advice, maintained provider coverage, or user adoption. Run from
the repository root after installing Rikdom. All calculations and reports work
offline. No source statements, portfolio files or service connections are needed
outside this directory.

The supported path uses explicit reviewed full-position statements. It does not
reconstruct missing historical units from current holdings. `statement.json` is
a manual normalized source input; `import-review.json` supplies the missing
account identities, distribution holding identity and explicit same-instant cash
transfer pair. Opening/closing evidence, a complete reviewed period ledger, and
opening lots are separately declared in `replay.json` and `basis.json`.
`portfolio.json` is a convenient authored copy of the reviewed identities before
split application; the commands below exercise actual import and review instead.

## Import and preserve the review

Use a scratch directory (Bash or Zsh):

```bash
task_history_dir="$(mktemp -d)"
cp -R data-sample/historical-workflow/. "$task_history_dir/"
cp "$task_history_dir/seed-portfolio.json" "$task_history_dir/portfolio.json"

uv run rikdom import-statement --plugin normalized-statement-json \
  --input "$task_history_dir/statement.json" \
  --portfolio "$task_history_dir/portfolio.json" \
  --review-file "$task_history_dir/import-review.json" \
  --data-dir "$task_history_dir/data" --import-log "$task_history_dir/imports.jsonl" \
  --ingested-at 2027-01-02T00:00:00Z --import-run-id reference-first --write

# Repeat the unchanged source without resupplying the review. Nine decisions survive.
uv run rikdom import-statement --plugin normalized-statement-json \
  --input "$task_history_dir/statement.json" \
  --portfolio "$task_history_dir/portfolio.json" \
  --data-dir "$task_history_dir/data" --import-log "$task_history_dir/imports.jsonl" \
  --ingested-at 2027-01-02T00:00:00Z --import-run-id reference-second --write
```

Four holdings and five source activities remain. Reviewed identities place the
outgoing transfer in account `a`, the incoming transfer in `b`, and the
USD distribution in holding `h` of account `a`. Similar money or dates alone
never establish a pair. Source contradictions require explicit resolution rather
than silently retaining an invalid review.

## Apply and revise the split

```bash
uv run rikdom market-events apply --input "$task_history_dir/market-events.json" \
  --event synthetic-fund-split --as-of 2027-01-01T00:00:00Z \
  --retrieved-before 2026-08-01T00:00:00Z \
  --portfolio "$task_history_dir/portfolio.json" \
  --review "$task_history_dir/split-review.json" --write

uv run rikdom market-events apply --input "$task_history_dir/market-events.json" \
  --event synthetic-fund-split --as-of 2027-01-01T00:00:00Z \
  --portfolio "$task_history_dir/portfolio.json" \
  --review "$task_history_dir/split-revision-review.json" --write
```

The original 2:1 event stays in the ledger. Its reviewed 3:1 replacement is the
single effective split. Repeating either already-applied review is a no-op.
The operation preserves current holdings and unadjusted quoted prices; it never
applies another multiplier to the independently supplied closing quantity 30.
No split-adjusted or total-return-adjusted price can value these quantities.

## Calculate the selected return and offline report

```bash
task_history_args=(
  --portfolio "$task_history_dir/portfolio.json"
  --snapshots "$task_history_dir/snapshots.jsonl"
  --historical-valuations "$task_history_dir/replay.json"
  --historical-fx "$task_history_dir/historical-fx.json"
  --flow-valuations "$task_history_dir/flow-valuations.json"
  --profit-basis "$task_history_dir/basis.json"
  --policy "$task_history_dir/policy.json"
  --benchmarks-dir "$task_history_dir/benchmarks"
  --data-dir "$task_history_dir/data"
)
uv run rikdom performance "${task_history_args[@]}"
uv run rikdom viz "${task_history_args[@]}" --out "$task_history_dir/report/dashboard.html"
```

The tracked `snapshots.jsonl` is deliberately empty. Explicit dated full-position
replay provides the two bookends. Before/after external-flow values are independent
source assertions in `flow-valuations.json`; they are not relabeled daily snapshots.
The required observations have age zero. Quotes, FX rates, effective/retrieved
times, instrument identities, source pointers and license declarations remain in
the selected output. A missing, future, stale or incompatible required quote makes
historical valuation and affected returns unavailable without a recorded-total or
current-holding fallback.

| Quantity | Hand check |
| --- | --- |
| Opening NAV, 2026-01-01 | `10 × USD 10 × 5 + BRL 100 = BRL 600` |
| Contribution, 2026-07-02 | `BRL 100`; NAV before/after `650 / 750` |
| Internal transfer, 2026-08-01 | `BRL 10` from `a` to `b`; zero portfolio external flow |
| Distribution, 2026-09-01 | USD 10 gross minus USD 2 withholding minus USD 1 fee = USD 7 cash |
| Withdrawal, 2027-01-01 | `BRL 50`; NAV before/after `1322 / 1272` |
| Closing NAV | `30 × USD 6 × 6 + BRL 140 + BRL 10 + USD 7 × 6 = BRL 1272` |
| Reconciled bridge | `600 + (100 − 50) + 622 = 1272` |
| Selected period TWR | `(650 / 600) × (1322 / 750) − 1 = 90.955556%` |
| Annualized 365-day XIRR | `96.923381%`; NPV `−600 − 100/(1+r)^(182/365) + 1322/(1+r) = 0` |
| Detailed result | BRL 480 unrealized price change + BRL 100 unrealized FX change + BRL 35 net income at receipt-date FX + BRL 7 cash FX = BRL 622 |
| Benchmark | USD total-return levels `100 → 110`, FX `5 → 6`: BRL return `32%`; comparable excess `58.955556` percentage points |

`twr_pct` retains legacy Modified Dietz. `twr_return_pct` is the selected linked
period return, with method and fallback disclosed; `mwr_pct` is annualized XIRR.
Full NAV includes received cash income and charges. The residual never adds
income again. Explicit net-marked income is not charged twice by the existing
basis engine. Detailed components remain unavailable if reviewed basis/history
is missing or unsupported, even when a bookend residual can be shown.
Bridge amounts use the existing decimal rounding convention and disclose any
rounding adjustment; the synthetic integer bridge needs none.

`replay.json` explicitly declares sourced full-NAV `total_return`; unadjusted
security prices alone cannot establish that convention. Removing the declaration
preserves the portfolio return while withholding benchmark excess. Foreign
benchmark bookends use the same exact dates and reporting currency.

The report's `quarto-input.json` section `sections.performance` equals the selected
CLI JSON, including evidence, warnings, calendar coverage, methods and treatment.
Keep the entire report directory when moving the offline HTML. Current holdings
valuation is a separate report section; missing monthly boundary statements stay
unavailable rather than being interpolated from these annual bookends.

## Capture, export, restore and replay

```bash
uv run rikdom capture-analysis "${task_history_args[@]}" --output "$task_history_dir/run"
uv run rikdom export-analysis --run "$task_history_dir/run" --output "$task_history_dir/run.zip"
uv run rikdom restore-analysis --bundle "$task_history_dir/run.zip" --output "$task_history_dir/restored"
uv run rikdom replay-analysis --run "$task_history_dir/restored"
```

The captured effective portfolio includes import-review and source-event evidence.
The run copies the exact required normalized calculation inputs, nested local
market cache and selected benchmark. Original source statement files are not
implicitly bundled. Replay requires the recorded compatible installed environment;
it never installs or executes bundled code. Redacted or omitted required evidence
cannot establish successful replay.

`tests.test_historical_reference_workflow` checks real import/reimport, split
revision idempotency, hand-computed amounts, investor NPV, unavailable adjusted
prices, explicit benchmark convention, exact CLI/report equality, and fresh-directory
bundle replay after deleting all original calculation files. Network connections
are denied throughout that test. Synthetic evidence establishes these mechanics
only; it does not independently verify any real statement's completeness.
