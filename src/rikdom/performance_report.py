"""One JSON contract for calculated performance consumed by CLI and reports.

Presentation may format or select these facts but must not recalculate returns,
interpret raw snapshot growth as profit, or add income to NAV a second time.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .historical_fx import HistoricalFx
from .performance import PerformanceResult, extract_external_cashflows, performance_result_to_dict


# These are the local files selected by the built-in report, independent of
# whether their contents produce an available performance section.
REPORT_PERFORMANCE_PATH_OPTIONS = {
    'flow_valuations': 'flow_valuations_path', 'historical_fx': 'historical_fx_path',
    'historical_valuations': 'historical_valuations_path', 'profit_basis': 'profit_basis_path',
    'fx_history': 'fx_history_path', 'policy': 'policy_path', 'benchmarks_dir': 'benchmarks_dir',
}
REPORT_ARTIFACT_NAMES = (
    'quarto-input.json', 'report-data.js', 'holding_trust.json', 'holding_trust.md',
    'reconciliation.json', 'reconciliation.md', 'dashboard.html', 'portfolio-report.html',
)


def protect_report_inputs(
    portfolio: dict[str, Any], *, portfolio_path: str | Path, snapshots_path: str | Path,
    output_dir: str | Path, options: dict[str, Any] | None = None,
    dashboard_path: str | Path | None = None,
    additional_inputs: tuple[str | Path, ...] = (),
) -> None:
    """Reject report targets aliasing selected inputs before any report write.

    Discover paths separately from calculation validation: malformed sidecars
    still belong to the caller. Embedded paths use the portfolio directory,
    overrides use the working directory, and caches use their config directory.
    This preflight covers the built-in report, not arbitrary trusted plugin code.
    """
    source_dir = Path(portfolio_path).resolve().parent
    extensions = portfolio.get('extensions')
    preferences = extensions.get('rikdom_report') if isinstance(extensions, dict) else None
    embedded = preferences.get('performance') if isinstance(preferences, dict) else None
    selected = {}
    if isinstance(embedded, dict):
        selected = {key: (value, source_dir) for key, value in embedded.items()
                    if key in REPORT_PERFORMANCE_PATH_OPTIONS.values()}
    selected.setdefault('fx_history_path', ('fx_rates.jsonl', source_dir))
    selected.setdefault('benchmarks_dir', ('benchmarks', source_dir))
    for name, value in (options or {}).items():
        key = REPORT_PERFORMANCE_PATH_OPTIONS.get(name, name)
        if key in REPORT_PERFORMANCE_PATH_OPTIONS.values():
            if isinstance(value, str) and value.strip() and '://' not in value:
                value = str(Path(value).resolve())
            selected[key] = (value, Path.cwd())

    paths = {}
    for key, (value, base) in selected.items():
        if isinstance(value, str) and value.strip() and '://' not in value:
            path = Path(value)
            paths[key] = path if path.is_absolute() else base / path
    inputs = [Path(portfolio_path), Path(snapshots_path), *(Path(path) for path in additional_inputs)]
    inputs.extend(path for key, path in paths.items() if key != 'benchmarks_dir')

    def local_document(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            # Validation and unavailable-section diagnostics remain the loader's
            # responsibility. The selected file itself is protected regardless.
            return None

    for key in ('historical_fx_path', 'historical_valuations_path'):
        if key not in paths:
            continue
        config_path = paths[key]
        config = local_document(config_path)
        reference = config.get('market_series_file') if isinstance(config, dict) else None
        if isinstance(reference, str) and reference.strip():
            cache = Path(reference)
            inputs.append(cache if cache.is_absolute() else config_path.parent / cache)
    if 'policy_path' in paths and 'benchmarks_dir' in paths:
        from .benchmarks import _is_safe_benchmark_id
        policy = local_document(paths['policy_path'])
        benchmarks = policy.get('benchmarks') if isinstance(policy, dict) else None
        if isinstance(benchmarks, list):
            base = paths['benchmarks_dir'].resolve()
            for benchmark in benchmarks:
                bid = benchmark.get('id') if isinstance(benchmark, dict) else None
                if isinstance(bid, str) and _is_safe_benchmark_id(bid):
                    inputs.append(base / f'{bid}.jsonl')

    targets = [Path(output_dir) / name for name in REPORT_ARTIFACT_NAMES]
    if dashboard_path is not None:
        targets.append(Path(dashboard_path))
    # Quarto derives support directories from the source .qmd names, even
    # when --output gives the rendered HTML a different name.
    asset_dirs = [Path(output_dir) / name for name in ('report_files', 'dashboard_files')]
    for tree in list(asset_dirs):
        if tree.is_dir():
            for path in tree.rglob('*'):
                if path.is_dir():
                    asset_dirs.append(path)
                else:
                    targets.append(path)
    for source in inputs:
        for directory in asset_dirs:
            if source.resolve().is_relative_to(directory.resolve()):
                raise ValueError(f'Report assets {directory} would overwrite input {source}')
    for target in targets:
        for source in inputs:
            if target.resolve() == source.resolve() or (
                target.exists() and source.exists() and target.samefile(source)
            ):
                raise ValueError(f'Report artifact {target} would overwrite input {source}')


def performance_to_dict(
    result: PerformanceResult, *, portfolio: dict[str, Any] | None = None,
    profit_basis: dict[str, Any] | None = None, historical_fx: HistoricalFx | None = None,
    valuation_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a detached result without changing legacy Dietz fields."""
    payload = performance_result_to_dict(result)
    payload['treatment'] = {
        'income': 'Included in portfolio valuations; never added to investment result again',
        'fees_taxes': 'Included to the extent reflected in supplied valuations and cashflows; no hypothetical liquidation tax',
        'cashflow_fx_status': 'Applies to external cashflow conversion only; does not verify historical valuation FX',
        'history': 'Results depend on supplied valuations and ledger; absent events do not prove complete real-world history',
        'twr': 'Selected period return; twr_pct retains the legacy Modified Dietz approximation',
        'mwr': 'Annualized XIRR on a 365-day year; short periods extrapolate',
    }
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
    from .internal_transfers import resolve_internal_transfers

    rows = []
    for activity in resolve_internal_transfers(activities).external_activities:
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
