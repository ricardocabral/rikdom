# Skill: Define Rikdom Investment Policy

Use this skill when the user wants to create, fill, define, review, or update `data/policy.json`, an Investment Policy Statement (IPS), objectives, target allocation, glide path, rebalancing rules, retirement assumptions, constraints, or guardrails.

## Purpose

Interview the user and produce a valid `data/policy.json` for a Rikdom portfolio. The policy is prescriptive configuration consumed by humans or agents during portfolio health checks and rebalancing reviews.

This skill does **not** provide regulated financial advice, execute trades, propose specific buy/sell orders, run imports, or edit `data/portfolio.json`.

## Scope

- Write only `data/policy.json` and, if useful for resumability, `data/.policy-interview.md`.
- Do not touch `data/portfolio.json`, snapshots, FX files, imports, plugins, or schema files.
- Do not edit `src/rikdom/_resources/policy.schema.json`. If the user needs a field the schema does not support, place it under `extensions` when allowed and flag it in the final report.
- Prefer local files only; do not fetch remote data to enrich assumptions.

## Required Context

Before asking detailed questions:

1. Ask for the portfolio data path if unknown:
   `What is your rikdom portfolio data path? You can send: (1) the data directory, (2) a full path to portfolio.json, or (3) workspace root + portfolio name.`
   If the user does not provide one, default to `data/` in the current workspace.
2. Read `src/rikdom/_resources/policy.schema.json` as the authoritative schema.
3. Read `data-sample/policy.json` as a realistic example and source of schema-shaped defaults.
4. If `<data-dir>/portfolio.json` exists, read it for defaults only: portfolio id/name, base currency, countries if present, account/provider hints, and rough AUM for guardrail sizing.
5. If `<data-dir>/policy.json` exists, treat this as an update: reuse existing values as defaults and only reconfirm stale, missing, or user-flagged sections.
6. If `<data-dir>/.policy-interview.md` exists, resume from it.

## Interview Rules

- Ask **one question at a time**.
- Offer 3–5 concrete options plus `other` whenever possible.
- Keep explanations short and practical.
- Never dump the whole schema at the user.
- Never invent unconfirmed personal numbers. Ask, omit optional fields, or save as an open question.
- End each major section with a recap and ask: `save partial / continue / edit previous`.
- Write incrementally after every completed section so progress is not lost.

## Interview Order

Cover every section, but allow `use defaults for this section` or `skip optional fields`.

1. **Identity**
   - `portfolio_id`
   - `policy_id`
   - `owner_kind`
   - `residence_country`
   - `tax_jurisdictions` (may differ from residence, e.g. US person abroad)
   - `policy_base_currency`

2. **Investor profile**
   - `birth_date` or age range if the user refuses exact date
   - `retirement_target_age` or `retirement_target_date`
   - `investment_horizon_years`
   - `risk_tolerance` (emotional comfort with volatility)
   - `risk_capacity` (financial ability to absorb loss)
   - `liquidity_needs_months`
   - `income_stability`
   - `dependents`
   - `tax_lot_method`

3. **Accounts**
   Catalog every wrapper/account type: taxable brokerage, PGBL/VGBL, 401k/IRA, previdência fechada, offshore, crypto custody, cash, or other.
   For each account collect:
   - `account_id`, `label`, optional `provider`
   - `jurisdiction`
   - `tax_account_type`
   - tax flags such as `tax_deferred`, `tax_free_withdrawals`, `early_withdrawal_penalty`
   - `preferred_holdings` hints for tax-aware placement

4. **Objectives**
   Always ask about:
   - retirement
   - emergency fund
   Then ask whether to include education, home purchase, legacy, sabbatical, healthcare, or other goals.
   For each objective collect kind, priority, target date/age if known, target amount if known, and funding accounts.

5. **Retirement assumptions**
   Explain real vs nominal spending in one sentence, then collect:
   - desired annual spending and currency
   - spending basis (`today`/real vs future/nominal)
   - inflation assumption and index reference (e.g. BR IPCA, US CPI)
   - target real/nominal return assumptions
   - withdrawal rule preference: fixed SWR, Guyton-Klinger, VPW, or other
   - longevity planning age
   - social security/pension sources
   - at least one stress scenario

6. **Strategic allocation**
   - Choose dimensions first: `asset_class` default, plus optional `region`, `currency`, `sector`, `factor`.
   - For each bucket collect `weight_pct`, `min_pct`, `max_pct`, and optional `rebalance_priority`.
   - Validate that each dimension sums to approximately 100, using the schema's rounding tolerance when present.

7. **Glide path**
   - Choose `static`, `age_based`, or `date_based`.
   - If age-based, propose waypoints at current age, pre-retirement, retirement, and late retirement.
   - Offer the heuristic `stocks_pct ≈ 110 − age` only as a starting point, never as a rule.

8. **Rebalancing policy**
   - Method (`calendar`, `threshold`, or `hybrid` when supported)
   - Cadence
   - Drift triggers: absolute percentage points and/or relative percent
   - Contribution-first behavior
   - Tax-awareness preferences
   - No-sell windows or cooling-off periods

9. **Cashflow policy**
   - Recurring contributions: amount, currency, cadence, destination/routing
   - Withdrawals: planned amount, cadence, source order, or deferred until retirement

10. **Constraints and exclusions**
    - Excluded tickers, sectors, countries, assets, leverage, derivatives, crypto, single-name caps
    - ESG/screens if any
    - Concentration caps
    - Currency exposure and hedging preferences

11. **Guardrails**
    This is the section future agents should cite most. Collect:
    - emergency fund floor as amount and months
    - maximum drawdown action
    - human confirmation threshold for any future action recommendation
    - concentration alert threshold
    - forbidden actions
    - behavioral rules such as cooling-off periods or no panic selling

12. **Review policy**
    - Review cadence
    - Triggers: birthday, job change, birth/death, marriage/divorce, move countries, major drawdown, inheritance, tax-law change, major market regime change

## Writing And Validation

After every section:

1. Update `<data-dir>/policy.json` using pretty JSON with stable indentation.
2. Preserve existing values unless the user explicitly changes them.
3. Set/update provenance when the schema supports it:
   - `provenance.llm_assisted: true`
   - `provenance.llm_model`
   - `provenance.created_at` only on first creation
   - `provenance.updated_at` on every write, in UTC
4. Validate with the project validator:

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

If the user's data directory is not `data`, substitute the correct path. If validation fails, fix schema-shape issues immediately and re-ask only for missing or ambiguous user intent.

## Final Report

When finished, provide a short Markdown report with:

1. **Coverage matrix** — populated, defaulted, skipped, or open for each major section.
2. **Consistency checks** — allocation sums per dimension, min/max bands, glide path monotonicity, emergency fund vs liquidity months where possible, human confirmation threshold vs rough AUM where available.
3. **Drift snapshot** — only if `portfolio.json` exists and current weights can be computed locally; flag outside-band buckets only. Do not propose trades.
4. **Open questions** — deferred assumptions, missing values, unsupported schema needs.

## Privacy And Safety

- Do not echo real account numbers, government IDs, addresses, or other sensitive PII in reports, docs, tests, or commits.
- Real identifiers belong only in local `data/policy.json` if the user explicitly wants them there.
- Use synthetic examples in any tracked sample files.
- State uncertainty clearly; the policy encodes user preferences and assumptions, not a guarantee of outcomes.
