"""One JSON contract for calculated performance consumed by CLI and reports.

Presentation may format or select these facts but must not recalculate returns,
interpret raw snapshot growth as profit, or add income to NAV a second time.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .activities import effective_activities
from .benchmarks import BenchmarkComparison
from .historical_fx import HistoricalFx
from .performance import PerformanceResult, extract_external_cashflows


def benchmark_comparison_to_dict(comp: BenchmarkComparison) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'benchmark_id': comp.benchmark_id, 'label': comp.label, 'kind': comp.kind,
        'currency': comp.currency, 'twr_pct': comp.twr_pct, 'excess_pct': comp.excess_pct,
    }
    if comp.comparison_status != 'legacy':
        payload.update(
            period_start=comp.period_start, period_end=comp.period_end,
            native_currency=comp.native_currency, native_twr_pct=comp.native_twr_pct,
            return_convention=comp.return_convention, fx_evidence=comp.fx_evidence,
            data_provenance=comp.data_provenance, comparison_status=comp.comparison_status,
        )
    if comp.warnings:
        payload['warnings'] = comp.warnings
    if comp.components:
        payload['components'] = [benchmark_comparison_to_dict(c) for c in comp.components]
    return deepcopy(payload)


def performance_to_dict(
    result: PerformanceResult, *, portfolio: dict[str, Any] | None = None,
    profit_basis: dict[str, Any] | None = None, historical_fx: HistoricalFx | None = None,
    valuation_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a detached result without changing legacy Dietz fields."""
    payload = {name: getattr(result, name) for name in (
        'base_currency', 'period_start', 'period_end', 'start_value_base', 'end_value_base',
        'net_external_cashflow_base', 'twr_pct', 'legacy_twr_method', 'twr_return_pct',
        'linked_twr_pct', 'twr_method', 'twr_fallback_reason', 'twr_return_basis',
        'mwr_return_basis', 'mwr_pct', 'cashflow_count', 'warnings', 'fx_status', 'fx_evidence',
    )}
    payload['mwr_method'] = 'xirr'
    payload['treatment'] = {
        'income': 'Included in portfolio valuations; never added to investment result again',
        'fees_taxes': 'Included to the extent reflected in supplied valuations and cashflows; no hypothetical liquidation tax',
        'cashflow_fx_status': 'Applies to external cashflow conversion only; does not verify historical valuation FX',
        'history': 'Results depend on supplied valuations and ledger; absent events do not prove complete real-world history',
        'twr': 'Selected period return; twr_pct retains the legacy Modified Dietz approximation',
        'mwr': 'Annualized XIRR on a 365-day year; short periods extrapolate',
    }
    if result.benchmarks:
        payload['benchmarks'] = [benchmark_comparison_to_dict(b) for b in result.benchmarks]
    if portfolio is not None:
        from .profit_attribution import compute_profit_attribution
        payload['profit_attribution'] = compute_profit_attribution(
            portfolio, result, basis=profit_basis, historical_fx=historical_fx,
        )
    if valuation_replay is not None:
        payload['valuation_replay'] = valuation_replay
        payload['valuation_status'] = valuation_replay['status']
        if valuation_replay['status'] != 'complete':
            for name in ('start_value_base', 'end_value_base', 'net_external_cashflow_base'):
                payload[name] = None
            payload['warnings'] = list(payload['warnings']) + [
                'Historical valuation unavailable; required prices, FX or position coverage are missing. No recorded snapshot fallback was used.'
            ]
    else:
        payload['valuation_status'] = 'recorded_unverified'
    return deepcopy(payload)


def load_performance_inputs(options: dict[str, Any], *, base_currency: str) -> dict[str, Any]:
    """Read only explicitly supplied local sidecars with identical CLI/report rules."""
    from .historical_fx import load_historical_fx
    from .performance import parse_flow_valuations, read_flow_valuations

    result = {'historical_fx': None, 'flow_valuations': None, 'profit_basis': None,
              'valuation_replay': None}
    for name in result:
        option_name = 'historical_valuations' if name == 'valuation_replay' else name
        path = options.get(option_name)
        if not path:
            continue
        try:
            if name == 'historical_fx':
                result[name] = load_historical_fx(path, base_currency=base_currency)
            elif name == 'flow_valuations':
                result[name] = read_flow_valuations(path)
                parse_flow_valuations(result[name], base_currency)
            elif name == 'profit_basis':
                from .profit_attribution import load_profit_basis
                result[name] = load_profit_basis(path)
            else:
                from .historical_valuation import replay_historical_valuations
                result[name] = replay_historical_valuations(path, base_currency=base_currency)
        except (OSError, ValueError) as exc:
            raise ValueError(f"--{option_name.replace('_', '-')}: {exc}") from exc
    return result


def recorded_contributions(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Show signed native external flows accepted by the calculation extractor.

    The extractor controls event taxonomy, posting status, signs and effective
    dates. Native-currency display makes no implicit FX or entitlement claim.
    """
    rows = []
    for activity in effective_activities(activities):
        money = activity.get('money')
        currency = money.get('currency') if isinstance(money, dict) else None
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            continue
        currency = currency.strip().upper()
        flows, _warnings = extract_external_cashflows([activity], currency)
        if not flows:
            continue
        rows.append({
            'activity_id': activity.get('id'), 'event_type': activity.get('event_type'),
            'date': str(activity.get('effective_at', ''))[:10],
            'account_id': activity.get('account_id'), 'asset_type_id': activity.get('asset_type_id'),
            'currency': currency, 'amount': flows[0].amount_base,
        })
    return rows
