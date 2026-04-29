# LLM Grounding Plan

Plan for landing the four highest-leverage schema improvements that let an LLM
agent ground portfolio analysis and advice in fact rather than guess. Status
as of 2026-04-29.

Each step is a self-contained slice: schema (or its policy equivalent) + any
migration needed + validator + fixtures + docs + tests, with `make check`
green before moving to the next.

## Current state baseline

- Portfolio schema is at `1.3.0`; readers accept `[1.0.0, 1.3.0]`.
- The `1.3.0` migration already announced optional slots for
  `holdings[].account_id`, `tax_lots[]`, and `liabilities[]`. The JSON Schema
  declares these fields and the structural validator covers basic shape
  (`src/rikdom/validate.py:251-372`).
- Policy schema lives at `src/rikdom/_resources/policy.schema.json`, currently
  `0.1.0`. There is no policy migration framework yet — only portfolio
  migrations under `src/rikdom/migrations/`.
- Activity `event_type` enum already covers
  `buy|sell|dividend|interest|fee|transfer_in|transfer_out|split|income|reimbursement|other`.

## Sequencing

1. **Step 1 — Wire `holdings[].account_id`** (no schema bump).
2. **Step 2 — Activity event taxonomy + cost-basis links** (portfolio
   `1.3.0 → 1.4.0`).
3. **Step 3 — Benchmarks per strategic bucket** (policy `0.1.0 → 0.2.0`,
   introduces policy migration framework).
4. **Step 4 — Tax rules table** (policy `0.2.0 → 0.3.0`).

## Step 1 — Wire `holdings[].account_id`

**Goal.** Make the policy-side `accounts[]` definitions usable by readers and
agents: every holding can declare which account it lives in, and validation
catches dangling references when both files are present.

**Why no schema bump.** The `account_id` field is already accepted at the
schema level and validated structurally. We are adding cross-file checking
plus sample data, not new shape.

**Changes.**

- `src/rikdom/validate.py`: extend `validate_portfolio` (or add a sibling
  `validate_portfolio_against_policy`) so when a policy is supplied, every
  `holdings[].account_id`, `liabilities[].account_id`, `tax_lots[].account_id`,
  and `activities[].account_id` (added below in step 2) is checked against
  `policy.accounts[].account_id`. Unknown ids become hard errors; missing
  ids become a soft warning surfaced in `validate.py`'s warnings channel.
- `src/rikdom/cli.py`: when both `--portfolio` and `--policy-path` are given
  to `validate`, run the cross-file check. Default behaviour unchanged when
  only one file is present.
- `src/rikdom/aggregate.py`: add an `accounts` roll-up to the aggregate
  output (`by_account.{account_id}.market_value_base`,
  `by_account_unassigned.market_value_base`). Pure additive; no schema in
  the snapshot file changes yet.
- `data-sample/portfolio.json`: assign `account_id` to every holding so the
  sample exercises the new wiring. Keep amounts unchanged.
- `tests/`: a new test module covering: unknown account_id is rejected,
  unassigned holdings produce a warning + appear under `by_account_unassigned`,
  aggregate per-account totals match brute-force sum.

**Done when.** `make check` is green and `make aggregate` shows
`by_account` totals for the sample portfolio.

## Step 2 — Activity event taxonomy + cost-basis links

**Goal.** Make the activity ledger expressive enough to reconstruct cash
flows, dividends/income, fees, taxes withheld, and FX conversions, and to
link sells to the tax lots they consumed.

**Schema bump.** Portfolio `1.3.0 → 1.4.0`.

**Changes.**

- `schema/portfolio.schema.json` activity object:
  - Add to `event_type` enum: `tax_withheld`, `fx_conversion`,
    `contribution`, `withdrawal`, `merger`.
  - Add optional fields:
    - `account_id` (soft reference to policy account).
    - `holding_id` (soft reference to `holdings[].id`; required on
      buy/sell/dividend/interest/split/merger when the activity targets a
      single holding).
    - `tax_lot_ids: string[]` — lots consumed by a sell or transferred by
      transfer_out (validated against `tax_lots[].id`).
    - `withholding_tax: Money` — for dividend / interest events.
    - `fx_rate: number` and `counter_money: Money` — for fx_conversion.
    - `realized_gain: Money` — for sell events; agents may compute it but
      the import path can also assert the broker's reported number.
- `src/rikdom/validate.py`: structural extension + semantic checks
  (`tax_lot_ids` must exist; `holding_id` must exist; `fx_conversion`
  requires `counter_money`; `tax_withheld` requires `money` ≥ 0).
- `src/rikdom/migrations/v1_3_0_to_v1_4_0.py`: pure version bump (no shape
  rewrites — all new fields are optional). Add to `MIGRATIONS` list.
- `src/rikdom/validate.py`: bump `CURRENT_SCHEMA_VERSION` to `(1, 4, 0)`.
- `data-sample/portfolio.json`: extend with an example dividend (with
  withholding), sell (with `tax_lot_ids` + `realized_gain`), and
  fx_conversion. Keep totals self-consistent.
- `docs/migrations.md`: append a row in the migration table (if any).
- `tests/`: round-trip migration test + validator unit tests for each new
  event_type and the new semantic checks.

**Done when.** `make migrate-dry-run` shows the new step, `make
validate-fixture` passes against the extended fixture, and `make test` is
green.

## Step 3 — Benchmarks per strategic bucket

**Goal.** Let the policy declare a benchmark per strategic-allocation bucket
so an agent can compute attribution and answer "how am I doing vs my own
target index?" without inventing tickers.

**Schema bump.** Policy `0.1.0 → 0.2.0`. This is the first policy
migration — it introduces a small policy migration framework.

**Changes.**

- `src/rikdom/_resources/policy.schema.json`:
  - New top-level optional `benchmarks: Benchmark[]` registry. Each
    `Benchmark` has `id`, `label`, `kind`
    (`index|etf|fund|composite|cash_rate`), `currency`, optional
    `ticker`, `index_code`, `provider`, `notes`, and an optional
    `composite` sub-object for blended benchmarks
    (`components: [{benchmark_id, weight_pct}]`).
  - On each `strategic_allocation.targets[]` entry, optional
    `benchmark_id` (must resolve in `benchmarks[]`).
- `src/rikdom/policy.py`: add semantic checks — every `benchmark_id` on a
  target resolves; composite benchmark weights sum to ~100; no cycles in
  composites.
- **Policy migration framework**:
  - Reuse `src/rikdom/migrations/base.py` (the `Migration` dataclass and
    version helpers are policy-agnostic).
  - Introduce `src/rikdom/migrations/policy/__init__.py` exporting a
    `POLICY_MIGRATIONS` registry plus `plan_policy_migrations` /
    `apply_policy_migrations` mirrors of the portfolio helpers.
  - First migration file:
    `src/rikdom/migrations/policy/v0_1_0_to_v0_2_0.py` — pure version
    bump.
  - Add `CURRENT_POLICY_SCHEMA_VERSION` and
    `MIN_COMPATIBLE_POLICY_SCHEMA_VERSION` constants to `policy.py` and
    enforce them in `validate_policy`.
  - Extend `rikdom migrate` CLI: new `--target policy|portfolio` flag (or
    a sibling `migrate-policy` subcommand mirroring `migrate`'s flags).
- `data-sample/policy.json`: declare a couple of benchmarks (CDI, IBOV,
  S&P 500, ACWI ex-US) and link a few targets to them.
- `docs/migrations.md`: document the policy track.
- `.claude/skills/define-policy/SKILL.md`: append a small section asking
  the user for benchmarks during the strategic-allocation interview.
- `tests/`: planner contiguity, round-trip, validator tests for unknown
  `benchmark_id`, composite cycle, weights summing to 100.

**Done when.** `uv run rikdom migrate-policy --portfolio data/policy.json
--dry-run` works, `validate_policy` accepts the extended fixture, and
`make test` is green.

## Step 4 — Tax rules table

**Goal.** Encode the BR/US tax facts the agent currently has to invent:
rates per `(tax_account_type, asset_class, holding_period_days, event_kind)`
plus effective-date windows.

**Schema bump.** Policy `0.2.0 → 0.3.0`.

**Changes.**

- `src/rikdom/_resources/policy.schema.json`:
  - New top-level optional `tax_rules: TaxRule[]`. Each `TaxRule` has
    `id`, `label`, `jurisdiction` (ISO-2), `applies_to`
    (`{tax_account_types?, asset_classes?, holding_period_days_min?,
    holding_period_days_max?, event_kinds?}`), `rate_pct`, optional
    `flat_amount` Money, `effective_from`, `effective_to`,
    `notes`, `source_url`. `event_kinds` enum mirrors the activity
    event_type enum where it makes sense (`sell`, `dividend`, `interest`,
    `withdrawal`, `come_cotas`, …).
  - Optional `exemptions: TaxExemption[]` (e.g., BR R$20k/month stock
    sales) with structured threshold, period, scope.
- `src/rikdom/policy.py`: semantic checks — `effective_from <=
  effective_to`; non-overlapping rules per same key (warning, not error);
  `applies_to.tax_account_types` resolves against `accounts[].tax_account_type`.
- `src/rikdom/migrations/policy/v0_2_0_to_v0_3_0.py`: version bump only.
- `data-sample/policy.json`: a small but realistic tax-rule set
  (BR stocks 15%, day-trade 20%, FII 20%, offshore stocks 15%,
  fixed-income regressive 22.5/20/17.5/15, come-cotas semiannual,
  IRPF salary brackets). All synthetic — no PII.
- `tests/`: validator coverage for `applies_to` mismatches, overlap
  warning, round-trip migration.
- `.claude/skills/define-policy/SKILL.md`: brief addition describing
  when to populate `tax_rules` (default to skip if user is unsure;
  agents should treat absence as "ask the user before using a number").

**Done when.** `make check` green, `make migrate-dry-run` (policy track)
shows the v0.2.0→v0.3.0 step, sample policy round-trips through both
policy migrations.

## Cross-cutting acceptance criteria

- `make check` green at the end of each step.
- No PII in any committed fixture; all amounts/identifiers synthetic.
- Backward compat preserved: an old `1.3.0` portfolio and `0.1.0` policy
  must still validate after each step (they will, because every new
  field is optional, but verified by tests).
- `unknown fields under metadata/extensions` survive every migration
  (covered by existing migration test base).
- All four steps land as separate commits with conventional-commit
  messages so the migration story is auditable.
