# define-policy

Interview the user to produce `data/policy.json` — the Investment Policy Statement (IPS) for this Rikdom portfolio. The file covers investor profile, retirement assumptions, strategic allocation, glide path, rebalancing rules, constraints, and guardrails. Consumed by other agents (human or LLM) during rebalancing and health checks.

## Scope

You write only `data/policy.json`. Do not touch `data/portfolio.json`, do not propose trades, do not run imports. The policy is prescriptive configuration.

## Inputs

1. Read `src/rikdom/_resources/policy.schema.json` — authoritative contract. Every field must validate.
2. Read `data-sample/policy.json` for a realistic example (BR-resident profile) to mirror when suggesting defaults.
3. If `data/portfolio.json` exists, read it for defaults (base currency, country, accounts inferable from `holdings[].identifiers.provider_account_id`, AUM for sizing guardrails).
4. If `data/policy.json` already exists, treat as update: reuse answers, reconfirm only stale ones.

## Interview flow

Ask **one question at a time**. Offer 3–5 concrete options plus "other". End each section with a recap and `save partial / continue / edit previous`.

Order — cover all sections but allow "use defaults for this section":

1. **Identity** — portfolio_id, residence_country, tax_jurisdictions (may differ for US persons abroad), policy_base_currency.
2. **Investor profile** — birth_date, retirement_target_age, risk_tolerance AND risk_capacity (separately: emotional vs financial), liquidity_needs_months, income_stability, dependents, tax_lot_method.
3. **Accounts** — every tax wrapper (taxable, PGBL/VGBL, 401k/IRA, previdência fechada, offshore, crypto self-custody). Per account: tax_account_type, jurisdiction, tax_deferred / tax_free_withdrawals / early_withdrawal_penalty, preferred_holdings hints. This enables tax-aware rebalancing later.
4. **Objectives** — probe retirement + emergency_fund as must-have; then education, home, legacy, sabbatical, healthcare.
5. **Retirement assumptions** — desired_annual_spending + spending_basis (explain real vs nominal), inflation_assumption_pct (BR IPCA≈4%, US CPI≈2.5% as defaults), target_real_return_pct, withdrawal_rule (explain: fixed SWR simple/brittle, Guyton-Klinger dynamic, VPW depletes), longevity_planning_age, social security/pension, ≥1 stress_scenario.
6. **Strategic allocation** — choose dimensions first (asset_class default; optional region/currency/sector/factor). Per bucket: weight_pct + min_pct/max_pct + rebalance_priority. Validate sum ≈ 100 per dimension.
7. **Glide path** — static / age_based / date_based. If age-based, propose waypoints at current age, pre-retirement, retirement, late retirement. Heuristic suggestion (never impose): stocks_pct ≈ 110 − age.
8. **Rebalancing policy** — method (hybrid usually), cadence, drift triggers absolute + relative, contribution_first, tax awareness, no-sell windows.
9. **Cashflow policy** — recurring contributions (amount, cadence, routing), withdrawals.
10. **Constraints & exclusions** — tickers/sectors/countries excluded, ESG screens, concentration caps, currency exposure + hedge policy.
11. **Guardrails** — emergency_fund_floor (Money + months), max_drawdown_action, require_human_confirmation_above, concentration_alert_pct, forbidden_actions, free-form behavioral_rules.
12. **Review policy** — cadence + triggers (birthday, job change, drawdown, life events).

## Writing the file

- Write `data/policy.json` incrementally after each section.
- Validate after each write with the project validator:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from rikdom.policy import validate_policy
path = Path('data/policy.json')
errors = validate_policy(json.loads(path.read_text()))
if errors:
    print('\n'.join(errors))
    raise SystemExit(1)
print('policy.json valid')
PY
```

If validation fails, fix and re-ask only failing fields.
- Set `provenance.llm_assisted: true`, `provenance.llm_model`, `provenance.created_at`/`updated_at` in UTC.
- Never invent unconfirmed numbers; omit optional fields rather than guess.

## Final deliverable

Emit a Markdown report:

1. **Coverage matrix** — sections populated vs skipped.
2. **Consistency checks** — sums per dimension, glide path monotonicity, emergency fund covers `liquidity_needs_months × monthly_expenses`, `require_human_confirmation_above` sensible vs AUM.
3. **Drift snapshot** (only if portfolio.json exists) — current vs target per bucket, flagging buckets outside bands. Do not propose trades.
4. **Open questions** — deferred items.

## Guardrails for this skill

- Inputs are local and trusted; do not call remote services to enrich answers.
- No PII in commits: real names/account numbers go only to `data/policy.json` (gitignored).
- Do not edit `schema/policy.schema.json`. If a needed field doesn't exist, use `extensions` and flag in the final report.
