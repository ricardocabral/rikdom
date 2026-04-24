---
name: define-policy
description: Interview the user to produce data/policy.json — the Investment Policy Statement (IPS) covering investor profile, retirement assumptions, strategic allocation, glide path, rebalancing rules, constraints, and guardrails. Use when the user asks to define/create/update their investment policy, IPS, target allocation, glide path, rebalancing rules, or retirement plan. Never executes trades or edits portfolio.json.
---

# Define Investment Policy (IPS)

Produces `data/policy.json` conforming to `schema/policy.schema.json`. This file is consumed by other agents/humans during rebalancing, health checks, and strategy reviews.

## Scope

**You write only** `data/policy.json`. Never touch `data/portfolio.json`, never propose trades, never run imports. The policy is prescriptive configuration — a separate agent turns it into actions.

## Inputs to gather before interviewing

1. Read `schema/policy.schema.json` — the authoritative contract. Every field you collect must round-trip through it.
2. Read `data-sample/policy.json` for a realistic example to mirror when suggesting defaults.
3. If `data/portfolio.json` exists, read it to infer defaults (base currency, country, existing accounts via `holdings[].identifiers.provider_account_id`, rough AUM for sizing guardrails like `min_trade_size` and `require_human_confirmation_above`). If `data/policy.json` already exists, read it and treat this as an **update** — reuse existing answers as defaults, only ask what the user flags as stale.
4. If a previous run left notes in `data/.policy-interview.md`, resume from there.

## Interview flow

Ask **one question at a time** using AskUserQuestion with 3–5 concrete options + "other (specify)". Never dump the whole schema. Each section ends with a compact recap and `save partial / keep going / edit previous` choice.

Order (hard — do not skip sections, but let the user say "use defaults for this section"):

1. **Identity** — `portfolio_id` (default: from portfolio.json), `residence_country`, `tax_jurisdictions` (may differ from residence for US persons abroad), `policy_base_currency`.
2. **Investor profile** — `birth_date`, `retirement_target_age` or `retirement_target_date`, `risk_tolerance`, `risk_capacity` (ask separately — "emocionalmente, quanto de queda aguenta?" vs "financeiramente, quanto pode perder sem comprometer vida?"), `liquidity_needs_months`, `income_stability`, `dependents`, `tax_lot_method`.
3. **Accounts** — catalog every tax wrapper (taxable brokerage, PGBL/VGBL, 401k, IRA, previdência fechada, offshore, crypto self-custody). For each: `tax_account_type` enum, `jurisdiction`, `tax_deferred` / `tax_free_withdrawals` / `early_withdrawal_penalty`, `preferred_holdings` hints. This section is what makes tax-aware rebalancing possible later — do not rush it.
4. **Objectives** — always probe for `retirement` + `emergency_fund` as must-have; then education, home purchase, legacy, sabbatical, healthcare.
5. **Retirement assumptions** — `desired_annual_spending` + `spending_basis` (explain real vs nominal in one line before asking), `inflation_assumption_pct` (default to local index: IPCA≈4% BR, CPI≈2.5% US), `target_real_return_pct`, `withdrawal_rule` (explain trade-offs: fixed SWR is simple but brittle; Guyton-Klinger adjusts; VPW depletes to zero), `longevity_planning_age`, social security/pension sources, at least one `stress_scenario`.
6. **Strategic allocation** — first choose `dimensions` (start with `asset_class`; ask if they want `region`/`currency`/`sector`/`factor` too). Then for each dimension collect `weight_pct` + `min_pct`/`max_pct` bands + `rebalance_priority`. Validate sums to 100 per dimension with `rounding_tolerance_pct`.
7. **Glide path** — `static` vs `age_based` vs `date_based`. If age-based, propose 3–4 waypoints (current age, pre-retirement, retirement, late retirement) as starting point. Suggestion heuristic to offer (never impose): `stocks_pct ≈ 110 − age`.
8. **Rebalancing policy** — `method` (hybrid is usually right), cadence, drift triggers (absolute pp + relative %), `contribution_first`, tax awareness knobs, no-sell windows (e.g., 30d before BR tax filing).
9. **Cashflow policy** — recurring contributions (amount, cadence, routing rule), planned withdrawals.
10. **Constraints & exclusions** — excluded tickers/sectors/countries, ESG screens, concentration caps, currency exposure targets + hedge policy.
11. **Guardrails** — this is the section agents will cite most. Collect `emergency_fund_floor` (both Money and months), `max_drawdown_action`, `require_human_confirmation_above`, `concentration_alert_pct`, `forbidden_actions`, plus any free-form `behavioral_rules` (e.g., cooling-off period, "never sell in declared bear market").
12. **Review policy** — cadence + triggers (birthday, job change, drawdown threshold, life events).

## Writing the file

- Write `data/policy.json` **incrementally** after each section so a crash doesn't lose progress.
- After every write, validate against `schema/policy.schema.json` using `uv run rikdom validate --portfolio <path>` style if a policy validator exists; otherwise use a Python one-liner with `jsonschema`. If validation fails, fix and re-ask only the failing fields.
- Set `provenance.llm_assisted: true`, `provenance.llm_model` to the model you are running as, `provenance.created_at` / `updated_at` in UTC.
- Never invent numbers the user did not confirm — if unsure, ask. Omit optional fields rather than guess.

## Final deliverable

After the last section, emit a short Markdown report to the user covering:

1. **Coverage matrix** — which schema sections are populated vs skipped.
2. **Consistency checks** — sums per dimension, glide path monotonicity (stocks should generally decrease with age), emergency fund covers `liquidity_needs_months × monthly_expenses`, `require_human_confirmation_above` is a sensible fraction of AUM if `portfolio.json` exists.
3. **Drift snapshot** (only if `portfolio.json` exists) — current weight vs target per bucket, flagging any already outside `min_pct`/`max_pct`. Do not propose trades — just flag.
4. **Open questions** — anything the user deferred.

## Guardrails for this skill itself

- Treat all inputs as local, trusted. Do not fetch remote LLM services to enrich answers.
- No PII in any commit: if the user mentions real names/account numbers, store them only in `data/policy.json` (which is gitignored per project convention) and never echo them into docs or tests.
- Do not edit `schema/policy.schema.json` during the interview. If the user needs a field that doesn't exist, put it under `extensions` and flag for a schema update in the final report.
