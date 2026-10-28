from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class FundedRatioResult:
    objective_id: str
    label: str
    kind: str | None
    priority: str
    target_date: str | None
    horizon_years: float
    target_amount_today_base: float | None
    projected_value_base: float
    ratio: float | None
    shortfall_base: float | None
    current_value_base: float
    net_annual_contribution_base: float
    expected_real_return_pct: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class FundedRatioSummary:
    base_currency: str
    as_of: str
    portfolio_value_base: float
    results: list[FundedRatioResult]
    warnings: list[str] = field(default_factory=list)


_FREQUENCY_PER_YEAR: dict[str, float] = {
    "monthly": 12.0,
    "quarterly": 4.0,
    "semiannual": 2.0,
    "yearly": 1.0,
}


def compute_funded_ratios(
    portfolio_value_base: float,
    policy: dict[str, Any],
    *,
    by_account: dict[str, float] | None = None,
    base_currency: str | None = None,
    fx_rates_to_base: dict[str, float] | None = None,
    as_of: date | str | None = None,
) -> FundedRatioSummary:
    """Compute deterministic funded ratios for policy objectives.

    The model is intentionally simple and auditable: each objective gets a
    current funded value, a real-return future value projection, and a target
    amount in today's base-currency purchasing power. It does not run Monte
    Carlo and does not infer tax effects.
    """

    as_of_date = _coerce_date(as_of) or date.today()
    warnings: list[str] = []
    if base_currency is None:
        base_currency = _policy_base_currency(policy)
    if not isinstance(base_currency, str) or not base_currency.strip():
        raise ValueError("An explicit base_currency is required")
    base_currency = base_currency.upper()
    fx_rates = _normalize_fx_rates(fx_rates_to_base)
    account_values = by_account or {}

    objectives = policy.get("objectives") if isinstance(policy, dict) else None
    if not isinstance(objectives, list) or not objectives:
        warnings.append("policy.objectives is empty; no funded ratios computed")
        return FundedRatioSummary(
            base_currency=base_currency,
            as_of=as_of_date.isoformat(),
            portfolio_value_base=float(portfolio_value_base),
            results=[],
            warnings=warnings,
        )

    expected_return_pct, return_warnings = _expected_real_return_pct(policy)
    warnings.extend(return_warnings)

    results: list[FundedRatioResult] = []
    for idx, objective in enumerate(objectives):
        if not isinstance(objective, dict):
            warnings.append(f"objectives[{idx}] is not an object; skipped")
            continue

        obj_warnings: list[str] = []
        oid = _string_or_default(objective.get("id"), f"objective-{idx}")
        label = _string_or_default(objective.get("label"), oid)
        priority = _string_or_default(objective.get("priority"), "unknown")
        kind = objective.get("kind") if isinstance(objective.get("kind"), str) else None

        target_date = _objective_target_date(
            objective, policy, as_of_date, obj_warnings
        )
        horizon_years = _years_until(as_of_date, target_date)

        target_amount = _objective_target_amount_today(
            objective,
            policy,
            base_currency=base_currency,
            fx_rates_to_base=fx_rates,
            horizon_years=horizon_years,
            warnings=obj_warnings,
            path=f"objectives[{idx}]",
        )

        current_value = _objective_current_value(
            objective,
            portfolio_value_base=float(portfolio_value_base),
            by_account=account_values,
            warnings=obj_warnings,
            path=f"objectives[{idx}]",
        )
        net_annual = _objective_net_annual_contribution(
            objective,
            policy,
            base_currency=base_currency,
            fx_rates_to_base=fx_rates,
            warnings=obj_warnings,
        )
        projected = _future_value(
            current_value,
            net_annual,
            expected_return_pct / 100.0,
            horizon_years,
        )

        ratio: float | None = None
        shortfall: float | None = None
        if target_amount is None:
            obj_warnings.append(
                "target amount unavailable; ratio and shortfall omitted"
            )
        elif target_amount <= 0:
            obj_warnings.append(
                "target amount is non-positive; ratio and shortfall omitted"
            )
        else:
            ratio = projected / target_amount
            shortfall = max(target_amount - projected, 0.0)

        results.append(
            FundedRatioResult(
                objective_id=oid,
                label=label,
                kind=kind,
                priority=priority,
                target_date=target_date.isoformat()
                if target_date is not None
                else None,
                horizon_years=round(horizon_years, 4),
                target_amount_today_base=_round_money(target_amount)
                if target_amount is not None
                else None,
                projected_value_base=float(projected),
                ratio=round(ratio, 6) if ratio is not None else None,
                shortfall_base=float(shortfall)
                if shortfall is not None
                else None,
                current_value_base=float(current_value),
                net_annual_contribution_base=float(net_annual),
                expected_real_return_pct=round(expected_return_pct, 6),
                warnings=obj_warnings,
            )
        )

    return FundedRatioSummary(
        base_currency=base_currency,
        as_of=as_of_date.isoformat(),
        portfolio_value_base=float(portfolio_value_base),
        results=results,
        warnings=warnings,
    )


def _policy_base_currency(policy: dict[str, Any]) -> str | None:
    identity = policy.get("identity")
    if isinstance(identity, dict):
        raw = identity.get("policy_base_currency")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().upper()
    return None


def _normalize_fx_rates(raw: dict[str, float] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for currency, rate in raw.items():
        if not isinstance(currency, str):
            continue
        if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0:
            out[currency.strip().upper()] = float(rate)
    return out


def _money_to_base(
    money: Any,
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
    path: str,
) -> float | None:
    if not isinstance(money, dict):
        warnings.append(f"{path} is missing Money amount/currency")
        return None
    amount = money.get("amount")
    currency = money.get("currency")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        warnings.append(f"{path}.amount is not numeric")
        return None
    if not isinstance(currency, str) or not currency.strip():
        warnings.append(f"{path}.currency is missing")
        return None
    code = currency.strip().upper()
    if code == base_currency:
        return float(amount)
    rate = fx_rates_to_base.get(code)
    if rate is None:
        warnings.append(
            f"{path} is in {code}; missing FX rate to {base_currency}, skipped"
        )
        return None
    return float(amount) * rate


def _annualize_money(
    item: dict[str, Any],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
    path: str,
) -> float:
    amount = _money_to_base(
        item.get("amount"),
        base_currency=base_currency,
        fx_rates_to_base=fx_rates_to_base,
        warnings=warnings,
        path=f"{path}.amount",
    )
    if amount is None:
        return 0.0
    cadence = item.get("cadence")
    frequency = cadence.get("frequency") if isinstance(cadence, dict) else None
    if frequency == "custom":
        warnings.append(
            f"{path}.cadence.frequency=custom cannot be annualized; skipped"
        )
        return 0.0
    per_year = (
        _FREQUENCY_PER_YEAR.get(frequency) if isinstance(frequency, str) else None
    )
    if per_year is None:
        warnings.append(f"{path}.cadence.frequency is missing or unsupported; skipped")
        return 0.0
    interval = cadence.get("interval", 1) if isinstance(cadence, dict) else 1
    if not isinstance(interval, int) or isinstance(interval, bool) or interval <= 0:
        warnings.append(f"{path}.cadence.interval must be a positive integer; skipped")
        return 0.0
    return amount * (per_year / interval)


def _objective_net_annual_contribution(
    objective: dict[str, Any],
    policy: dict[str, Any],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
) -> float:
    funding_accounts = _string_set(objective.get("funding_account_ids"))
    cashflow_policy = policy.get("cashflow_policy")
    if not isinstance(cashflow_policy, dict):
        return 0.0

    total = 0.0
    contributions = cashflow_policy.get("contributions")
    if isinstance(contributions, list):
        for idx, contribution in enumerate(contributions):
            if not isinstance(contribution, dict):
                continue
            account_id = contribution.get("account_id")
            if funding_accounts and account_id not in funding_accounts:
                continue
            total += _annualize_money(
                contribution,
                base_currency=base_currency,
                fx_rates_to_base=fx_rates_to_base,
                warnings=warnings,
                path=f"cashflow_policy.contributions[{idx}]",
            )

    withdrawals = cashflow_policy.get("withdrawals")
    if isinstance(withdrawals, list):
        for idx, withdrawal in enumerate(withdrawals):
            if not isinstance(withdrawal, dict):
                continue
            source_priority = _string_set(withdrawal.get("source_priority"))
            if (
                funding_accounts
                and source_priority
                and not (funding_accounts & source_priority)
            ):
                continue
            total -= _annualize_money(
                withdrawal,
                base_currency=base_currency,
                fx_rates_to_base=fx_rates_to_base,
                warnings=warnings,
                path=f"cashflow_policy.withdrawals[{idx}]",
            )
    return total


def _objective_current_value(
    objective: dict[str, Any],
    *,
    portfolio_value_base: float,
    by_account: dict[str, float],
    warnings: list[str],
    path: str,
) -> float:
    funding_accounts = _string_set(objective.get("funding_account_ids"))
    if not funding_accounts:
        return portfolio_value_base
    if not by_account:
        warnings.append(
            f"{path}.funding_account_ids provided but aggregate by_account is empty; "
            "using full portfolio value"
        )
        return portfolio_value_base

    total = 0.0
    for account_id in sorted(funding_accounts):
        value = by_account.get(account_id)
        if value is None:
            warnings.append(
                f"{path}.funding_account_ids references empty account '{account_id}'"
            )
            continue
        total += float(value)
    return total


def _objective_target_amount_today(
    objective: dict[str, Any],
    policy: dict[str, Any],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
    horizon_years: float,
    warnings: list[str],
    path: str,
) -> float | None:
    if "target_amount" in objective:
        return _money_to_base(
            objective.get("target_amount"),
            base_currency=base_currency,
            fx_rates_to_base=fx_rates_to_base,
            warnings=warnings,
            path=f"{path}.target_amount",
        )

    kind = objective.get("kind")
    if kind == "emergency_fund":
        guardrails = policy.get("guardrails")
        emergency = (
            guardrails.get("emergency_fund_floor")
            if isinstance(guardrails, dict)
            else None
        )
        if isinstance(emergency, dict) and "amount" in emergency:
            return _money_to_base(
                emergency.get("amount"),
                base_currency=base_currency,
                fx_rates_to_base=fx_rates_to_base,
                warnings=warnings,
                path="guardrails.emergency_fund_floor.amount",
            )
        warnings.append(
            "emergency_fund objective has no target_amount or guardrail floor"
        )
        return None

    if kind == "retirement":
        annual_spending = _retirement_annual_spending_today(
            policy,
            base_currency=base_currency,
            fx_rates_to_base=fx_rates_to_base,
            horizon_years=horizon_years,
            warnings=warnings,
        )
        if annual_spending is None:
            return None
        assumptions = policy.get("retirement_assumptions")
        withdrawal_rule = (
            assumptions.get("withdrawal_rule")
            if isinstance(assumptions, dict)
            else None
        )
        initial_rate = (
            withdrawal_rule.get("initial_rate_pct")
            if isinstance(withdrawal_rule, dict)
            else None
        )
        if (
            not isinstance(initial_rate, (int, float))
            or isinstance(initial_rate, bool)
            or initial_rate <= 0
        ):
            warnings.append(
                "retirement target requires retirement_assumptions.withdrawal_rule.initial_rate_pct"
            )
            return None
        return annual_spending / (float(initial_rate) / 100.0)

    warnings.append(
        f"{path} has no target_amount and kind '{kind}' has no derived target"
    )
    return None


def _retirement_annual_spending_today(
    policy: dict[str, Any],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
    horizon_years: float,
    warnings: list[str],
) -> float | None:
    spending_plan = policy.get("spending_plan")
    total: float | None = None
    if isinstance(spending_plan, dict):
        total = 0.0
        basis = _basis_or_today(spending_plan.get("basis"))
        for key in ("essentials", "discretionary", "healthcare"):
            line = spending_plan.get(key)
            if not isinstance(line, dict) or "annual_amount" not in line:
                continue
            amount = _money_to_base(
                line.get("annual_amount"),
                base_currency=base_currency,
                fx_rates_to_base=fx_rates_to_base,
                warnings=warnings,
                path=f"spending_plan.{key}.annual_amount",
            )
            if amount is None:
                continue
            if basis == "at_retirement":
                inflation_pct = _spending_line_inflation_pct(
                    line,
                    spending_plan=spending_plan,
                    policy=policy,
                    warnings=warnings,
                    path=f"spending_plan.{key}",
                )
                if inflation_pct is None:
                    return None
                amount = _deflate_at_retirement_amount(
                    amount,
                    inflation_pct=inflation_pct,
                    horizon_years=horizon_years,
                )
            total += amount
        multiplier = _retirement_phase_multiplier_pct(policy)
        if multiplier is not None:
            total *= multiplier / 100.0
        if total > 0:
            return _subtract_retirement_income(
                total,
                policy,
                base_currency=base_currency,
                fx_rates_to_base=fx_rates_to_base,
                warnings=warnings,
            )

    assumptions = policy.get("retirement_assumptions")
    if isinstance(assumptions, dict) and "desired_annual_spending" in assumptions:
        amount = _money_to_base(
            assumptions.get("desired_annual_spending"),
            base_currency=base_currency,
            fx_rates_to_base=fx_rates_to_base,
            warnings=warnings,
            path="retirement_assumptions.desired_annual_spending",
        )
        if amount is not None:
            if _basis_or_today(assumptions.get("spending_basis")) == "at_retirement":
                inflation_pct = _retirement_inflation_pct(
                    policy,
                    warnings=warnings,
                    path="retirement_assumptions.inflation_assumption_pct",
                )
                if inflation_pct is None:
                    return None
                amount = _deflate_at_retirement_amount(
                    amount,
                    inflation_pct=inflation_pct,
                    horizon_years=horizon_years,
                )
            return _subtract_retirement_income(
                amount,
                policy,
                base_currency=base_currency,
                fx_rates_to_base=fx_rates_to_base,
                warnings=warnings,
            )

    warnings.append("retirement annual spending unavailable")
    return None


def _basis_or_today(raw: Any) -> str:
    return raw if raw == "at_retirement" else "today"


def _deflate_at_retirement_amount(
    amount: float, *, inflation_pct: float, horizon_years: float
) -> float:
    if horizon_years <= 0:
        return amount
    return amount / ((1.0 + inflation_pct / 100.0) ** horizon_years)


def _retirement_inflation_pct(
    policy: dict[str, Any], *, warnings: list[str], path: str
) -> float | None:
    assumptions = policy.get("retirement_assumptions")
    value = (
        assumptions.get("inflation_assumption_pct")
        if isinstance(assumptions, dict)
        else None
    )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    warnings.append(f"{path} is required for at_retirement spending basis")
    return None


def _spending_line_inflation_pct(
    line: dict[str, Any],
    *,
    spending_plan: dict[str, Any],
    policy: dict[str, Any],
    warnings: list[str],
    path: str,
) -> float | None:
    value = line.get("inflation_pct")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    value = spending_plan.get("default_inflation_pct")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return _retirement_inflation_pct(
        policy,
        warnings=warnings,
        path=f"{path}.inflation_pct or spending_plan.default_inflation_pct",
    )


def _subtract_retirement_income(
    annual_spending: float,
    policy: dict[str, Any],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float],
    warnings: list[str],
) -> float:
    assumptions = policy.get("retirement_assumptions")
    pension = (
        assumptions.get("social_security_or_pension")
        if isinstance(assumptions, dict)
        else None
    )
    if not isinstance(pension, list):
        return annual_spending
    annual_income = 0.0
    for idx, item in enumerate(pension):
        if not isinstance(item, dict):
            continue
        monthly = _money_to_base(
            item.get("expected_monthly"),
            base_currency=base_currency,
            fx_rates_to_base=fx_rates_to_base,
            warnings=warnings,
            path=f"retirement_assumptions.social_security_or_pension[{idx}].expected_monthly",
        )
        if monthly is not None:
            annual_income += monthly * 12.0
    return max(annual_spending - annual_income, 0.0)


def _retirement_phase_multiplier_pct(policy: dict[str, Any]) -> float | None:
    target_age = _retirement_target_age(policy)
    spending_plan = policy.get("spending_plan")
    phases = spending_plan.get("phases") if isinstance(spending_plan, dict) else None
    if target_age is None or not isinstance(phases, list):
        return None
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        start = phase.get("start_age")
        end = phase.get("end_age", 999)
        multiplier = phase.get("multiplier_pct")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and isinstance(multiplier, (int, float))
            and not isinstance(multiplier, bool)
            and start <= target_age <= end
        ):
            return float(multiplier)
    return None


def _expected_real_return_pct(policy: dict[str, Any]) -> tuple[float, list[str]]:
    warnings: list[str] = []
    cma = policy.get("capital_market_assumptions")
    strategic = policy.get("strategic_allocation")
    if isinstance(cma, dict) and isinstance(strategic, dict):
        buckets = cma.get("buckets")
        targets = strategic.get("targets")
        if isinstance(buckets, list) and isinstance(targets, list):
            cma_by_bucket: dict[tuple[str, str], float] = {}
            for bucket in buckets:
                if not isinstance(bucket, dict):
                    continue
                dim = bucket.get("dimension")
                name = bucket.get("bucket")
                value = bucket.get("expected_real_return_pct")
                if (
                    isinstance(dim, str)
                    and isinstance(name, str)
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                ):
                    cma_by_bucket[(dim, name)] = float(value)
            weighted = 0.0
            covered_weight = 0.0
            for target in targets:
                if not isinstance(target, dict):
                    continue
                dim = target.get("dimension")
                name = target.get("bucket")
                weight = target.get("weight_pct")
                if (
                    not isinstance(dim, str)
                    or not isinstance(name, str)
                    or not isinstance(weight, (int, float))
                    or isinstance(weight, bool)
                ):
                    continue
                expected = cma_by_bucket.get((dim, name))
                if expected is None:
                    continue
                weighted += float(weight) * expected
                covered_weight += float(weight)
            if covered_weight > 0:
                if covered_weight < 99.5:
                    warnings.append(
                        "capital_market_assumptions cover only "
                        f"{covered_weight:.2f}% of strategic target weights; "
                        "normalizing covered weights"
                    )
                return weighted / covered_weight, warnings

    assumptions = policy.get("retirement_assumptions")
    if isinstance(assumptions, dict):
        value = assumptions.get("target_real_return_pct")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), warnings
    warnings.append("no real return assumption found; using 0% real return")
    return 0.0, warnings


def _objective_target_date(
    objective: dict[str, Any],
    policy: dict[str, Any],
    as_of: date,
    warnings: list[str],
) -> date | None:
    raw_target = objective.get("target_date")
    if isinstance(raw_target, str):
        parsed = _coerce_date(raw_target)
        if parsed is not None:
            return parsed
        warnings.append(f"invalid objective target_date '{raw_target}'")

    if objective.get("kind") == "retirement":
        investor = policy.get("investor_profile")
        if isinstance(investor, dict):
            raw = investor.get("retirement_target_date")
            if isinstance(raw, str):
                parsed = _coerce_date(raw)
                if parsed is not None:
                    return parsed
            birth = _coerce_date(investor.get("birth_date"))
            target_age = investor.get("retirement_target_age")
            if (
                birth is not None
                and isinstance(target_age, int)
                and not isinstance(target_age, bool)
            ):
                return _add_years(birth, target_age)
            horizon = investor.get("investment_horizon_years")
            if (
                isinstance(horizon, int)
                and not isinstance(horizon, bool)
                and horizon >= 0
            ):
                return _add_years(as_of, horizon)

    warnings.append("target date unavailable; using as_of date")
    return as_of


def _retirement_target_age(policy: dict[str, Any]) -> int | None:
    investor = policy.get("investor_profile")
    if isinstance(investor, dict):
        age = investor.get("retirement_target_age")
        if isinstance(age, int) and not isinstance(age, bool):
            return age
    return None


def _coerce_date(value: date | str | None) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap target years.
        return value.replace(month=2, day=28, year=value.year + years)


def _years_until(start: date, end: date | None) -> float:
    if end is None:
        return 0.0
    return max((end - start).days / 365.25, 0.0)


def _future_value(
    current_value: float,
    annual_contribution: float,
    annual_return: float,
    years: float,
) -> float:
    if years <= 0:
        return current_value
    growth = (1.0 + annual_return) ** years
    if abs(annual_return) < 1e-12:
        contributions_fv = annual_contribution * years
    else:
        contributions_fv = annual_contribution * ((growth - 1.0) / annual_return)
    return current_value * growth + contributions_fv


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _string_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _round_money(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value)
