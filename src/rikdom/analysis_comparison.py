"""Read-only comparison of recorded performance evidence; never a replay or return.

Only complete rikdom-analysis-run 1.0 performance directories are supported.
The public function hides integrity checks, evidence pointers, compatibility and
conservative isolation rules. Checksums establish integrity, not authorship or
correctness of recorded answers. No recorded environment or code is executed.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone

from .analysis_runs import (
    RUN_MANIFEST, AnalysisRunError, _benchmark_dependencies, _digest, _environment,
    _json_bytes, _read_verified_run, _strict_input,
)

_METRICS = ('start_value_base', 'end_value_base', 'net_external_cashflow_base',
            'twr_pct', 'twr_return_pct', 'linked_twr_pct', 'mwr_pct')
_METHODS = ('twr_method', 'legacy_twr_method', 'mwr_method', 'twr_return_basis',
            'mwr_return_basis', 'return_convention', 'treatment')
_FX_ROLES = {'fx_history', 'historical_fx', 'historical_fx.market_series_file'}
_RUNTIME_KEYS = ('python', 'implementation', 'platform', 'core_version', 'core_sha256',
                 'dependencies', 'plugins', 'package_version', 'module_version')
_VALUATION_ROLES = {'snapshots', 'historical_valuations',
                    'historical_valuations.market_series_file', 'flow_valuations'}


def _validate_role_documents(manifest: dict, documents: dict) -> None:
    """Bind copied documents to their supported roles without selecting or calculating."""
    from .performance import _finite_number, parse_flow_valuations
    from .market_series import _currency, _number, _text

    inputs = manifest['inputs']
    base = documents[inputs['portfolio']]['settings']['base_currency']
    _currency(base)
    for role in ('snapshots', 'fx_history'):
        rows = documents[inputs[role]]
        if not isinstance(rows, list):
            raise ValueError(f'{role}: expected JSONL records')
        for index, row in enumerate(rows):
            field = f'{role}[{index}]'
            try:
                if role == 'snapshots':
                    _text(row['timestamp'], 'timestamp')
                    datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                    if 'base_currency' in row:
                        _currency(row['base_currency'])
                    totals = row['totals']
                    if not isinstance(totals, dict):
                        raise ValueError('totals must be an object')
                    value = totals['portfolio_value_base']
                    if value is not None and _finite_number(value) is None:
                        raise ValueError('totals.portfolio_value_base must be a finite number or null')
                    if 'by_account' in totals:
                        if not isinstance(totals['by_account'], dict):
                            raise ValueError('totals.by_account must be an object')
                        for account, value in totals['by_account'].items():
                            _text(account, 'totals.by_account account identity')
                            if value is not None and _finite_number(value) is None:
                                raise ValueError('totals.by_account value must be a finite number or null')
                else:
                    _currency(row['base_currency'])
                    _currency(row['quote_currency'])
                    _number(row['rate_to_base'], positive=True)
                    _text(row['as_of_date'], 'as_of_date')
                    datetime.fromisoformat(row['as_of_date'])
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError(f'{field}: {exc}') from exc
    if 'flow_valuations' in inputs:
        parse_flow_valuations(documents[inputs['flow_valuations']], base)
    if 'policy' in inputs:
        accounts = documents[inputs['policy']].get('accounts', [])
        if not isinstance(accounts, list) or any(not isinstance(row, dict) or
                not isinstance(row.get('account_id'), str) or not row['account_id'].strip()
                for row in accounts):
            raise ValueError('policy.accounts requires objects with declared account_id')
    scope = manifest['parameters']['by']
    if scope != 'portfolio' and any(role in inputs for role in
            ('flow_valuations', 'historical_valuations', 'profit_basis')):
        raise ValueError('flow_valuations/historical_valuations/profit_basis require portfolio scope')
    if scope == 'instrument' and 'historical_fx' in inputs:
        raise ValueError('historical_fx does not support instrument scope')


def _validate_fx_evidence(rows: list[dict], result: dict, manifest: dict, documents: dict) -> None:
    """Bind published FX rows to captured events/quotes without selecting rates."""
    from .activities import effective_activities
    from .internal_transfers import resolve_internal_transfers
    from .market_series import _currency, _iso, _number, _parse_series, _text, _timestamp
    from .performance import _EXTERNAL_FLOW_SIGNS, _event_type, _finite_number, _is_posted, _parse_iso

    inputs = manifest['inputs']
    if 'historical_fx' not in inputs:
        if rows:
            raise ValueError('fx_evidence requires captured historical_fx')
        return
    config = documents[inputs['historical_fx']]
    nested = (PurePosixPath(inputs['historical_fx']).parent / config['market_series_file']).as_posix()
    series = dict(_parse_series(row) for row in documents[nested]['series'])
    ledger = effective_activities(documents[inputs['portfolio']].get('activities', []))
    bounds = [_parse_iso(result[field]) if result.get(field) else None
              for field in ('period_start', 'period_end')]
    ledger = resolve_internal_transfers(ledger, *bounds).external_activities
    events = {row['id']: row for row in ledger}
    seen = set()
    for index, row in enumerate(rows):
        try:
            required = {'activity_id', 'event_type', 'effective_at', 'native_amount',
                        'native_currency', 'amount_base', 'status', 'reason'}
            if not required <= row.keys() or row['status'] not in ('available', 'unavailable'):
                raise ValueError('missing required fields or unsupported status')
            aid = _text(row['activity_id'], 'activity_id')
            if aid not in events or aid in seen:
                raise ValueError('activity_id must identify one captured effective external event')
            seen.add(aid)
            event = events[aid]
            kind = _event_type(event)
            if not _is_posted(event) or kind not in _EXTERNAL_FLOW_SIGNS:
                raise ValueError('activity_id must identify a posted external flow')
            money = event.get('money')
            money = money if isinstance(money, dict) else {}
            raw_date = event.get('effective_at')
            expected = {'event_type': kind, 'effective_at': raw_date if isinstance(raw_date, str) else None,
                        'native_amount': _finite_number(money.get('amount')),
                        'native_currency': money.get('currency') if isinstance(money.get('currency'), str) else None}
            if any(row[key] != value for key, value in expected.items()):
                raise ValueError('event fields disagree with captured effective activity')
            try:
                if not isinstance(raw_date, str):
                    raise ValueError('missing effective_at')
                parsed = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError('naive effective_at')
                when = parsed.astimezone(timezone.utc)
            except ValueError:
                when = None  # Match historical cashflows: invalid/naive dates stay unavailable.
            if when is not None and ((bounds[0] and when < bounds[0]) or (bounds[1] and when > bounds[1])):
                raise ValueError('activity lies outside recorded resolved bookends')
            if row['status'] == 'unavailable':
                if row['amount_base'] is not None:
                    raise ValueError('unavailable conversion requires null amount_base')
                _text(row['reason'], 'reason')
            else:
                if row['native_amount'] is None or row['amount_base'] is None:
                    raise ValueError('available conversion requires native_amount and amount_base')
                if row['reason'] is not None or row.get('lookup_status') != 'available':
                    raise ValueError('available conversion requires successful lookup evidence')
            if 'lookup_status' not in row:
                if row['status'] != 'unavailable' or row['reason'] not in (
                        'invalid_effective_at', 'invalid_financial_amount', 'invalid_currency'):
                    raise ValueError('missing lookup_status')
                continue
            if row['lookup_status'] not in ('available', 'missing', 'stale'):
                raise ValueError('unsupported lookup_status')
            required = {'rate', 'as_of', 'currency_pair', 'retrieved_before', 'max_age_seconds'}
            if not required <= row.keys():
                raise ValueError('missing required lookup evidence fields')
            if row['lookup_status'] == 'available':
                _number(row['rate'], positive=True)
            elif row['rate'] is not None:
                raise ValueError('unavailable lookup requires null rate')
            native = _currency(row['native_currency'])
            if when is None or row.get('as_of') != _iso(when):
                raise ValueError('as_of must match the captured activity instant')
            if row.get('currency_pair') != {'base': native, 'quote': result['base_currency']}:
                raise ValueError('currency_pair disagrees with captured activity/result')
            cutoff = config['retrieved_before']
            cutoff = _iso(_timestamp(cutoff, 'retrieved_before')) if cutoff is not None else None
            if ('retrieved_before' not in row or row['retrieved_before'] != cutoff
                    or row.get('max_age_seconds') != config['max_age_seconds']):
                raise ValueError('FX selection parameters disagree with captured historical_fx')
            if native == result['base_currency']:
                if row.get('identity') is not True or row.get('rate') != 1:
                    raise ValueError('native FX requires identity rate evidence')
                continue
            if row['lookup_status'] in ('available', 'stale') or native in config['series_by_currency']:
                required = {'series_id', 'series', 'observation', 'superseded', 'age_seconds'}
                if not required <= row.keys():
                    raise ValueError('converted FX requires captured series and observation evidence')
                if row['lookup_status'] in ('available', 'stale') and (
                        row['observation'] is None or row['age_seconds'] is None):
                    raise ValueError('available/stale lookup requires observation and age evidence')
                if row['age_seconds'] is not None:
                    _number(row['age_seconds'], positive=False)
            if 'series_id' in row:
                sid = row['series_id']
                if sid != config['series_by_currency'].get(native):
                    raise ValueError('series_id disagrees with captured historical_fx mapping')
                captured = series.get(sid)
                if row.get('series') != (captured.metadata if captured else None):
                    raise ValueError('series disagrees with captured series metadata')
                observations = [item.payload for item in captured.observations] if captured else []
                observation = row.get('observation')
                if observation is not None and observation not in observations:
                    raise ValueError('observation must reference a captured normalized observation')
                superseded = row.get('superseded')
                if not isinstance(superseded, list) or any(item not in observations for item in superseded):
                    raise ValueError('superseded must reference captured observations')
                if row['status'] == 'available' and row['rate'] != observation['value']:
                    raise ValueError('rate disagrees with captured observation')
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'fx_evidence[{index}]: {exc}') from exc


def _validate_result_evidence(result: dict, manifest: dict, documents: dict) -> None:
    """Check published field contracts and declared support, never financial truth."""
    def objects(value: Any, field: str) -> list[dict]:
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise ValueError(field + ' must be an array of objects')
        return value

    def status(value: dict, field: str) -> None:
        if not isinstance(value, dict) or not isinstance(value.get('status'), str):
            raise ValueError(field + '.status must be a string')

    def number(value: Any, field: str) -> None:
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError(field + ' must be a finite number or null')

    inputs = manifest['inputs']
    if manifest['parameters']['by'] == 'instrument':
        rows = objects(result['by_instrument'], 'by_instrument')
        for index, row in enumerate(rows):
            field = f'by_instrument[{index}]'
            status(row, field)
            for key in ('holding_id', 'currency'):
                if not isinstance(row.get(key), str):
                    raise ValueError(field + '.' + key + ' must be a string')
            if row.get('valuation_basis') is not None and not isinstance(row['valuation_basis'], str):
                raise ValueError(field + '.valuation_basis must be a string or null')
            if not isinstance(row.get('warnings'), list) or any(not isinstance(item, str) for item in row['warnings']):
                raise ValueError(field + '.warnings must be an array of strings')
            objects(row.get('cashflows'), field + '.cashflows')
            for key in ('terminal_value', 'profit_amount', 'xirr_pct'):
                number(row.get(key), field + '.' + key)
            if row['status'] == 'complete':
                holdings = documents[inputs['portfolio']].get('holdings', [])
                matches = [holding for holding in holdings if holding.get('id') == row['holding_id']]
                history = (matches[0].get('extensions') or {}).get('rikdom_instrument_history') if len(matches) == 1 else None
                if not isinstance(history, dict) or history.get('status') != 'complete' or history.get('missing_periods') != []:
                    raise ValueError(field + ' complete requires captured holding history declared complete')
        return
    fx_rows = objects(result.get('fx_evidence'), 'fx_evidence')
    for index, row in enumerate(fx_rows):
        status(row, f'fx_evidence[{index}]')
        for key in ('rate', 'native_amount', 'amount_base'):
            if key in row:
                number(row[key], f'fx_evidence[{index}].{key}')
    _validate_fx_evidence(fx_rows, result, manifest, documents)
    objects(result.get('return_convention_evidence'), 'return_convention_evidence')
    if result['twr_method'] == 'linked_subperiod':
        if 'flow_valuations' not in inputs:
            raise ValueError('linked_subperiod requires captured flow_valuations')
        if not documents[inputs['flow_valuations']]['valuations']:
            raise ValueError('linked_subperiod requires nonempty flow_valuations.valuations')
    if result['fx_status'] == 'complete':
        if 'historical_fx' not in inputs:
            raise ValueError('fx_status complete requires captured historical_fx')
        if len(fx_rows) != result.get('cashflow_count') or any(row['status'] != 'available' for row in fx_rows):
            raise ValueError('fx_status complete requires available fx_evidence for captured cashflow_count')
    replay = result.get('valuation_replay')
    if replay is not None:
        status(replay, 'valuation_replay')
        objects(replay.get('snapshots'), 'valuation_replay.snapshots')
        objects(replay.get('valuations'), 'valuation_replay.valuations')
        if 'historical_valuations' not in inputs:
            raise ValueError('valuation_replay requires captured historical_valuations')
        if result['valuation_status'] != replay['status']:
            raise ValueError('valuation_status disagrees with valuation_replay.status')
    if result['valuation_status'] == 'complete':
        if 'historical_valuations' not in inputs or replay is None or replay['status'] != 'complete':
            raise ValueError('valuation_status complete requires captured historical_valuations and valuation_replay')
        for row in documents[inputs['historical_valuations']]['snapshots']:
            if row['positions_complete'] is not True:
                raise ValueError('historical_valuations.snapshots.positions_complete required for complete valuation_status')
        if not replay['snapshots'] or not replay['valuations']:
            raise ValueError('valuation_replay complete requires snapshots and valuations')
        for row in replay['valuations']:
            if row.get('status') != 'complete' or row.get('positions_complete') is not True:
                raise ValueError('valuation_replay.valuations requires complete status and positions_complete')
    attribution = result.get('profit_attribution')
    if attribution is not None:
        status(attribution, 'profit_attribution')
        for key in ('bridge', 'decomposition'):
            section = attribution.get(key)
            status(section, 'profit_attribution.' + key)
            for field in ('cashflow_evidence', 'holdings', 'activity_evidence', 'cash_evidence', 'fx_evidence'):
                if field in section:
                    objects(section[field], 'profit_attribution.' + key + '.' + field)
            from .profit_attribution import _COMPONENTS
            from .multicurrency_profit import FX_COMPONENTS
            for field in (*_COMPONENTS, *FX_COMPONENTS, 'opening_value_base', 'closing_value_base',
                          'net_external_cashflow_base', 'investment_result_base'):
                if field in section:
                    number(section[field], 'profit_attribution.' + key + '.' + field)
        if attribution['decomposition']['status'] == 'complete':
            if 'profit_basis' not in inputs:
                raise ValueError('profit_attribution.decomposition complete requires captured profit_basis')
            basis = documents[inputs['profit_basis']]
            if basis.get('contract_version') not in ('1.0', '2.0') or basis.get('scope') != 'portfolio':
                raise ValueError('profit_basis requires supported contract_version and portfolio scope')
            constants = {'base_currency': result['base_currency'], 'method': 'fifo',
                         'price_adjustment': 'unadjusted',
                         'cost_convention': 'buy_costs_capitalized_sell_costs_deducted'}
            if any(basis.get(key) != value for key, value in constants.items()):
                raise ValueError('profit_basis requires supported currency, method and adjustment/cost conventions')
            decomposition = attribution['decomposition']
            if (attribution.get('base_currency') != result['base_currency']
                    or attribution.get('scope') != manifest['parameters']['by']):
                raise ValueError('profit_attribution currency/scope disagrees with recorded result/parameters')
            review, history = basis.get('review'), basis.get('history')
            if not isinstance(review, dict) or review.get('status') != 'reviewed' or not review.get('source'):
                raise ValueError('profit_basis.review must declare reviewed evidence and source')
            if not isinstance(history, dict) or history.get('status') != 'complete' or history.get('missing_periods') != []:
                raise ValueError('profit_basis.history must declare complete history with no missing_periods')
            for field, value in (('period_start', history.get('from')), ('period_end', history.get('through'))):
                from .profit_attribution import _timestamp
                expected = _timestamp(result[field])
                if (_timestamp(basis[field]) != expected or _timestamp(value) != expected
                        or _timestamp(attribution.get(field)) != expected):
                    raise ValueError('profit_basis.history and attribution period must match recorded ' + field)
            if basis['contract_version'] == '2.0':
                inventory = basis.get('inventory')
                if not isinstance(inventory, dict) or inventory.get('status') != 'complete':
                    raise ValueError('profit_basis.inventory must declare complete inventory')
            if (decomposition.get('method') != basis['method']
                    or decomposition.get('contract_version', '1.0') != basis['contract_version']
                    or decomposition.get('basis_evidence') != basis):
                raise ValueError('profit_attribution.decomposition disagrees with captured profit_basis')


def _account_scope(manifest: dict, payloads: dict, portfolio: dict, result: dict) -> dict:
    """Retain declared account identities and explicitly unassigned canonical rows."""
    identities = set()
    unassigned = False
    by_role = {}
    unassigned_by_role = {}
    for collection in ('holdings', 'activities'):
        rows = portfolio.get(collection, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise AnalysisRunError(f'Invalid portfolio {collection}: expected objects')
        declared = set()
        unassigned_by_role[collection] = False
        for row in rows:
            identity = row.get('account_id')
            if identity is None or (isinstance(identity, str) and not identity.strip()) or identity == '__unassigned__':
                unassigned = True
                unassigned_by_role[collection] = True
            elif not isinstance(identity, str):
                raise AnalysisRunError(f'Invalid {collection}.account_id')
            else:
                declared.add(identity)
        identities.update(declared)
        by_role[collection] = sorted(declared) if declared else None
    snapshots = [json.loads(line) for line in payloads[manifest['inputs']['snapshots']].splitlines()
                 if line.strip()]
    declared = set()
    for row in snapshots:
        declared.update(row['totals'].get('by_account', {}))
    if '__unassigned__' in declared:
        unassigned = True
        declared.remove('__unassigned__')
    identities.update(declared)
    by_role['snapshots'] = sorted(declared) if declared else None
    if 'policy' in manifest['inputs']:
        policy = json.loads(payloads[manifest['inputs']['policy']])
        declared = {row['account_id'] for row in policy.get('accounts', [])}
        identities.update(declared)
        by_role['policy'] = sorted(declared) if declared else None
    # Replay replaces the journal's numerical bookends. Its supported v1 full
    # positions have no account membership; do not infer it from position IDs.
    if 'historical_valuations' in manifest['inputs']:
        snapshots = []
    from .performance import _parse_iso
    declared = set()
    if result.get('period_start') and result.get('period_end'):
        start, end = (_parse_iso(result[field]) for field in ('period_start', 'period_end'))
        for row in snapshots:
            if start <= _parse_iso(row['timestamp']) <= end:
                declared.update(row['totals'].get('by_account', {}))
    unassigned_by_role['snapshots_in_resolved_window'] = '__unassigned__' in declared
    by_role['snapshots_in_resolved_window'] = sorted(declared - {'__unassigned__'}) or None
    bookends = {}
    for field in ('period_start', 'period_end'):
        when = result.get(field)
        memberships = [row['totals'].get('by_account') for row in snapshots
                       if when and _parse_iso(row['timestamp']) == _parse_iso(when)]
        declared_memberships = [sorted(row) if row else None for row in memberships]
        if declared_memberships and any(row != declared_memberships[0] for row in declared_memberships):
            raise ValueError('Conflicting snapshot account membership at resolved ' + field)
        membership = declared_memberships[0] if declared_memberships else None
        bookends[field] = None if membership is None else {
            'account_ids': [identity for identity in membership if identity != '__unassigned__'],
            'has_unassigned_accounts': '__unassigned__' in membership}
    return {'account_ids': sorted(identities) if identities else None,
            'has_unassigned_accounts': unassigned, 'account_ids_by_evidence': by_role,
            'has_unassigned_accounts_by_evidence': unassigned_by_role,
            'account_membership_at_bookends': bookends}


def _read_evidence(path: str | Path) -> tuple[dict, dict[str, bytes]]:
    """Reuse verified capture bytes, then enforce the bounded comparison contract."""
    try:
        manifest, payloads = _read_verified_run(path, check_environment=False)
        documents = {}
        for name, data in payloads.items():
            _strict_input(data, name, jsonl=name.endswith('.jsonl'))
            if name.endswith('.jsonl'):
                documents[name] = [json.loads(line) for line in data.splitlines() if line.strip()]
            else:
                documents[name] = json.loads(data)
            _json_bytes(documents[name])  # Reject numeric overflow as well as NaN/Infinity.
        if manifest.get('omitted'):
            raise ValueError('Required analysis evidence omitted')
        environment = manifest['environment']
        for key in ('python', 'implementation', 'platform', 'core_version', 'core_sha256',
                    'package_version', 'module_version', 'plugin_execution', 'trust_boundary'):
            if not isinstance(environment[key], str) or not environment[key]:
                raise ValueError('Invalid recorded environment: ' + key)
        for key in ('dependencies', 'dependency_lock_references', 'access'):
            if not isinstance(environment[key], dict):
                raise ValueError('Invalid recorded environment: ' + key)
        if any(value is not None and not isinstance(value, str)
               for value in environment['dependencies'].values()):
            raise ValueError('Invalid recorded dependency versions')
        if any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
               for value in environment['dependency_lock_references'].values()):
            raise ValueError('Invalid recorded dependency lock references')
        if not isinstance(environment['plugins'], list) or not re.fullmatch('[a-f0-9]{64}', environment['core_sha256']):
            raise ValueError('Invalid recorded environment inventory')
        expected = {'result.json': 'expected_result'}
        for role, name in manifest['inputs'].items():
            if role != 'benchmarks_dir':
                expected[name] = role
            if role in ('historical_fx', 'historical_valuations'):
                config = documents[name]
                nested = (PurePosixPath(name).parent / config['market_series_file']).as_posix()
                expected[nested] = role + '.market_series_file'
                from .market_series import parse_market_series
                series = parse_market_series(documents[nested])
                if role == 'historical_fx':
                    fields = {'contract_version', 'market_series_file', 'series_by_currency',
                              'max_age_seconds', 'retrieved_before'}
                    if set(config) != fields or config['contract_version'] != '1.0':
                        raise ValueError('Unsupported or malformed historical FX contract')
                    # Constructor validation only; no rate selection or calculation.
                    from .historical_fx import HistoricalFx
                    HistoricalFx(series, base_currency=documents[manifest['inputs']['portfolio']]['settings']['base_currency'],
                                 series_by_currency=config['series_by_currency'],
                                 max_age_seconds=config['max_age_seconds'],
                                 retrieved_before=config['retrieved_before'])
                else:
                    fields = {'contract_version', 'market_series_file', 'price_max_age_seconds',
                              'fx_max_age_seconds', 'retrieved_before', 'series_by_currency', 'snapshots'}
                    if 'return_convention' in config:
                        fields.add('return_convention')
                    if set(config) != fields or config['contract_version'] != '1.0':
                        raise ValueError('Unsupported or malformed historical valuation contract')
                    from .historical_valuation import _validate_snapshots
                    from .historical_fx import HistoricalFx
                    from .market_series import _number
                    _validate_snapshots(config['snapshots'])
                    _number(config['price_max_age_seconds'], positive=False)
                    HistoricalFx(series, base_currency=documents[manifest['inputs']['portfolio']]['settings']['base_currency'],
                                 series_by_currency=config['series_by_currency'],
                                 max_age_seconds=config['fx_max_age_seconds'],
                                 retrieved_before=config['retrieved_before'])
        policy = documents.get(manifest['inputs'].get('policy'), {})
        for identifier in _benchmark_dependencies(policy):
            expected[manifest['inputs']['benchmarks_dir'] + '/' + identifier + '.jsonl'] = 'benchmark'
        if set(expected) != set(manifest['files']):
            raise ValueError('Unsupported or missing analysis file inventory')
        for name, role in expected.items():
            evidence = manifest['files'][name]
            if (evidence['role'] != role or type(evidence['bytes']) is not int
                    or evidence['bytes'] < 0 or not re.fullmatch('[a-f0-9]{64}', evidence['sha256'])
                    or ('original_sha256' in evidence and not re.fullmatch('[a-f0-9]{64}', evidence['original_sha256']))):
                raise ValueError('Invalid analysis file evidence: ' + name)
        portfolio = documents[manifest['inputs']['portfolio']]
        from .activities import check_financial_contract
        check_financial_contract(portfolio)
        for key in ('metadata', 'extensions', 'settings', 'profile'):
            if key in portfolio and not isinstance(portfolio[key], dict):
                raise ValueError('Invalid portfolio ' + key)
        rows = portfolio.get('activities', [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                                            or not row['id'] for row in rows):
            raise ValueError('Comparison requires identified activity records')
        if len({row['id'] for row in rows}) != len(rows):
            raise ValueError('Comparison requires unique activity identities')
        for row in rows:
            if 'extensions' in row and not isinstance(row['extensions'], dict):
                raise ValueError('Invalid activity extensions')
        _validate_role_documents(manifest, documents)
        retained = portfolio.get('extensions', {}).get('rikdom_reviewed_imports')
        if retained is not None:
            if not isinstance(retained, dict) or type(retained.get('version')) is not int or retained['version'] != 1:
                raise ValueError('Unsupported reviewed import evidence')
            for key in ('revisions', 'decisions'):
                if not isinstance(retained[key], list) or any(not isinstance(row, dict) for row in retained[key]):
                    raise ValueError('Invalid reviewed import ' + key)
            for revision in retained['revisions']:
                for key in ('source_revision', 'source_payload_hash', 'content_hash'):
                    if not re.fullmatch('[a-f0-9]{64}', revision[key]):
                        raise ValueError('Invalid reviewed source revision')
        diagnostics = portfolio.get('extensions', {}).get('rikdom_import_diagnostics')
        if diagnostics is not None:
            from .import_preflight import validate_import_diagnostics
            if (not isinstance(diagnostics, dict) or type(diagnostics.get('version')) is not int
                    or diagnostics['version'] != 1 or not isinstance(diagnostics['statements'], dict)):
                raise ValueError('Invalid retained import diagnostics')
            for value in diagnostics['statements'].values():
                if validate_import_diagnostics(value):
                    raise ValueError('Invalid retained statement diagnostics')
        if not isinstance(manifest['created_at'], str):
            raise ValueError('Missing capture timestamp')
        datetime.fromisoformat(manifest['created_at'].replace('Z', '+00:00'))
        parameters = manifest['parameters']
        if not isinstance(parameters['analysis_as_of'], str):
            raise ValueError('Missing captured FX selection timestamp')
        if parameters['instrument'] is not None and not isinstance(parameters['instrument'], str):
            raise ValueError('Invalid instrument parameter')
        terminal = parameters['terminal_value']
        if terminal is not None and (type(terminal) not in (int, float) or not math.isfinite(terminal)):
            raise ValueError('Invalid terminal value parameter')
        if parameters['by'] not in ('portfolio', 'account', 'strategic_bucket', 'instrument'):
            raise ValueError('Unsupported performance scope')
        for key in ('since', 'until', 'analysis_as_of'):
            if parameters[key] is not None:
                datetime.fromisoformat(parameters[key].replace('Z', '+00:00'))
        result = documents['result.json']
        if not isinstance(result.get('warnings'), list) or any(not isinstance(item, str) for item in result['warnings']):
            raise ValueError('Invalid recorded warnings')
        methods = manifest['methods']
        method_keys = {'twr_method', 'mwr_method', 'twr_return_basis', 'mwr_return_basis'}
        if parameters['by'] == 'instrument':
            if not isinstance(result['by_instrument'], list) or methods != {}:
                raise ValueError('Invalid instrument result evidence')
        else:
            if set(methods) != method_keys or any(methods[key] != result[key] for key in method_keys):
                raise ValueError('Recorded methods disagree with result')
            for key in (*method_keys, 'legacy_twr_method', 'return_convention', 'base_currency',
                        'period_start', 'period_end', 'fx_status', 'valuation_status'):
                if not isinstance(result[key], str):
                    raise ValueError('Invalid recorded result: ' + key)
            for key in ('profit_attribution', 'valuation_replay'):
                if key in result and not isinstance(result[key], dict):
                    raise ValueError('Invalid recorded evidence: ' + key)
            if not isinstance(result['treatment'], dict):
                raise ValueError('Invalid recorded treatment semantics')
            if not re.fullmatch('[A-Z]{3}', result['base_currency']):
                raise ValueError('Invalid recorded reporting currency')
            if result['base_currency'] != portfolio['settings']['base_currency']:
                raise ValueError('Recorded result currency disagrees with captured portfolio')
            for key in ('period_start', 'period_end'):
                if result[key]:
                    datetime.fromisoformat(result[key].replace('Z', '+00:00'))
            for metric in _METRICS:
                value = result[metric]
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                    raise ValueError('Invalid recorded metric: ' + metric)
        _validate_result_evidence(result, manifest, documents)
        _account_scope(manifest, payloads, portfolio, result)
        return manifest, payloads
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, AnalysisRunError):
            raise
        raise AnalysisRunError(f'Invalid or unavailable analysis comparison evidence: {exc}') from exc

def _reference(path: str, payloads: dict[str, bytes], pointer: str = '') -> dict[str, Any]:
    return {'path': path, 'pointer': pointer, 'sha256': _digest(payloads[path])}

def _activity_changes(old: dict, new: dict, old_path: str, new_path: str,
                      old_bytes: dict, new_bytes: dict) -> dict[str, list]:
    def indexed(portfolio: dict, path: str, payloads: dict) -> dict:
        return {row['id']: (row, {'id': row['id'],
                'evidence': _reference(path, payloads, f'/activities/{index}'),
                'source_ref': row.get('source_ref'), 'provenance': row.get('provenance'),
                'correction': (row.get('extensions') or {}).get('rikdom_correction')})
                for index, row in enumerate(portfolio.get('activities', []))}
    a, b = indexed(old, old_path, old_bytes), indexed(new, new_path, new_bytes)
    return {'added': [b[key][1] for key in sorted(b.keys() - a.keys())],
            'removed': [a[key][1] for key in sorted(a.keys() - b.keys())],
            'modified': [{'id': key, 'before': a[key][1], 'after': b[key][1]}
                         for key in sorted(a.keys() & b.keys()) if a[key][0] != b[key][0]]}

def _source_reviews(portfolio: dict, path: str, payloads: dict) -> list[dict]:
    retained = (portfolio.get('extensions') or {}).get('rikdom_reviewed_imports', {})
    revisions = []
    for index, revision in enumerate(retained.get('revisions', [])):
        revisions.append({key: revision.get(key) for key in
                          ('version', 'source_revision', 'source_payload_hash', 'content_hash')})
        revisions[-1]['evidence'] = _reference(
            path, payloads, f'/extensions/rikdom_reviewed_imports/revisions/{index}')
    for index, decision in enumerate(retained.get('decisions', [])):
        revisions.append({key: decision.get(key) for key in
                          ('id', 'status', 'source_revision', 'accepted_source_revision')})
        revisions[-1]['evidence'] = _reference(
            path, payloads, f'/extensions/rikdom_reviewed_imports/decisions/{index}')
    return revisions

def _coverage(result: dict, portfolio: dict) -> dict:
    statements = portfolio.get('extensions', {}).get('rikdom_import_diagnostics', {}).get('statements', {})
    return {'valuation_status': result.get('valuation_status'),
            'fx_status': result.get('fx_status'), 'warnings': result.get('warnings'),
            'history_coverage': ([item for value in statements.values() for item in value['history_coverage']]
                                 if statements else None),
            'unsupported_events': ([item for value in statements.values() for item in value['unsupported_events']]
                                   if statements else None),
            'profit_attribution_status': (result.get('profit_attribution') or {}).get('status'),
            'valuation_replay_coverage': (result.get('valuation_replay') or {}).get('coverage'),
            'limitation': 'Absent coverage is unknown; recorded snapshots do not verify historical valuations or ledger completeness.'}


def _controlled_fx_revision(a: dict, b: dict, a_bytes: dict, b_bytes: dict) -> bool:
    """Only cutoff changes or append-only revisions with the FX contract held fixed."""
    if 'historical_fx' not in a['inputs'] or 'historical_fx' not in b['inputs']:
        return False
    configs = [json.loads(payloads[manifest['inputs']['historical_fx']])
               for manifest, payloads in ((a, a_bytes), (b, b_bytes))]
    if ({key: value for key, value in configs[0].items() if key != 'retrieved_before'} !=
            {key: value for key, value in configs[1].items() if key != 'retrieved_before'}):
        return False
    series = [json.loads(payloads[(PurePosixPath(manifest['inputs']['historical_fx']).parent /
                                  config['market_series_file']).as_posix()])
              for manifest, payloads, config in ((a, a_bytes, configs[0]), (b, b_bytes, configs[1]))]
    if series[0] == series[1]:
        return configs[0]['retrieved_before'] != configs[1]['retrieved_before']
    if configs[0] != configs[1] or len(series[0]['series']) != len(series[1]['series']):
        return False
    added = False
    for previous, current in zip(series[0]['series'], series[1]['series']):
        if ({key: value for key, value in previous.items() if key != 'observations'} !=
                {key: value for key, value in current.items() if key != 'observations'}):
            return False
        old_rows, new_rows = previous['observations'], current['observations']
        if (len(new_rows) > len(old_rows) and (previous['kind'] != 'fx'
                or previous['id'] not in configs[0]['series_by_currency'].values())):
            return False
        if new_rows[:len(old_rows)] != old_rows or len(new_rows) < len(old_rows):
            return False
        known = {row['id']: row for row in old_rows}
        for row in new_rows[len(old_rows):]:
            target = known.get(row['supersedes'])
            if target is None or any(row[key] != target[key] for key in ('effective_at', 'currency')):
                return False
            known[row['id']] = row
            added = True
    return added

def compare_analysis_runs(before: str | Path, after: str | Path) -> dict[str, Any]:
    """Compare two captured answers, with deltas only for compatible summaries.

    Paths select run directories, including restored v2 archives. This function
    never calculates performance, loads foreign code, or writes any file. Invalid,
    omitted or unsupported evidence raises AnalysisRunError (an existing ValueError
    contract). Hashes and JSON pointers refer to the exact verified captured bytes.
    """
    captures = [_read_evidence(path) for path in (before, after)]
    (a, a_bytes), (b, b_bytes) = captures
    old, new = [json.loads(payloads['result.json']) for _, payloads in captures]
    old_path, new_path = a['inputs']['portfolio'], b['inputs']['portfolio']
    old_portfolio, new_portfolio = json.loads(a_bytes[old_path]), json.loads(b_bytes[new_path])
    runs = []
    installed = _environment()
    for path, (manifest, payloads), portfolio, result in zip(
            (before, after), captures, (old_portfolio, new_portfolio), (old, new)):
        runs.append({'run': {'directory': str(Path(path)), **_reference(RUN_MANIFEST, payloads)},
                     'inputs': [{'role': item['role'], **_reference(name, payloads),
                                 'original_sha256': item.get('original_sha256')}
                                for name, item in sorted(manifest['files'].items()) if name != 'result.json'],
                     'result': _reference('result.json', payloads),
                     'created_at': manifest['created_at'],
                     'scope': {'by': manifest['parameters']['by'],
                               'instrument': manifest['parameters']['instrument'],
                               'portfolio_id': portfolio.get('profile', {}).get('portfolio_id'),
                               **_account_scope(manifest, payloads, portfolio, result)},
                     'period_start': result.get('period_start'), 'period_end': result.get('period_end'),
                     'base_currency': result.get('base_currency'),
                     'input_sha256': _digest(_json_bytes({'inputs': manifest['inputs'],
                         'files': {name: evidence for name, evidence in manifest['files'].items() if name != 'result.json'}})),
                     'parameters': manifest['parameters'], 'methods': manifest['methods'],
                     'environment': manifest['environment'],
                     'runtime_compatibility': {'mismatches': [key for key in _RUNTIME_KEYS
                         if manifest['environment'][key] != installed[key]]},
                     'evidence': {key: _reference('result.json', payloads, '/' + key)
                                  for key in ('fx_evidence', 'valuation_replay', 'profit_attribution',
                                              'return_convention_evidence', 'warnings')
                                  if key in result},
                     'source_reviews': _source_reviews(portfolio, manifest['inputs']['portfolio'], payloads)})
        runs[-1]['evidence'].update({key: _reference(RUN_MANIFEST, payloads, '/' + key)
                                    for key in ('parameters', 'methods', 'environment', 'inputs')})
        if 'rikdom_import_diagnostics' in portfolio.get('extensions', {}):
            runs[-1]['evidence']['history_coverage'] = _reference(
                manifest['inputs']['portfolio'], payloads, '/extensions/rikdom_import_diagnostics')
    files = []
    for name in sorted(a['files'].keys() | b['files'].keys()):
        if name == 'result.json' or a['files'].get(name) == b['files'].get(name):
            continue
        files.append({'before': ({'role': a['files'][name]['role'], **_reference(name, a_bytes)}
                                 if name in a['files'] else None),
                      'after': ({'role': b['files'][name]['role'], **_reference(name, b_bytes)}
                                if name in b['files'] else None)})
    mapping_changes = sorted(key for key in a['inputs'].keys() | b['inputs'].keys()
                             if a['inputs'].get(key) != b['inputs'].get(key))
    roles = sorted({side['role'] for item in files for side in (item['before'], item['after']) if side}
                   | set(mapping_changes))
    parameter_changes = [key for key in sorted(a['parameters']) if a['parameters'][key] != b['parameters'][key]]
    method_changes = [key for key in _METHODS if old.get(key) != new.get(key)]
    environment_changes = [key for key in sorted(a['environment'].keys() | b['environment'].keys())
                           if a['environment'].get(key) != b['environment'].get(key)]
    activities = _activity_changes(old_portfolio, new_portfolio, old_path, new_path, a_bytes, b_bytes)
    sections = [key for key in sorted(old_portfolio.keys() | new_portfolio.keys())
                if old_portfolio.get(key) != new_portfolio.get(key)]
    coverage = {'before': _coverage(old, old_portfolio), 'after': _coverage(new, new_portfolio)}
    coverage['changed'] = coverage['before'] != coverage['after']
    reasons = []
    if a['parameters']['by'] != b['parameters']['by'] or a['parameters']['instrument'] != b['parameters']['instrument']:
        reasons.append('scope_changed')
    if a['parameters']['by'] != 'portfolio' or b['parameters']['by'] != 'portfolio':
        reasons.append('numerical_scope_unsupported')
    for portfolio in (old_portfolio, new_portfolio):
        if not (portfolio.get('profile') or {}).get('portfolio_id'):
            reasons.append('portfolio_identity_unknown')
            break
    if ((old_portfolio.get('profile') or {}).get('portfolio_id') !=
            (new_portfolio.get('profile') or {}).get('portfolio_id')):
        reasons.append('portfolio_identity_changed')
    if (any(runs[0]['scope']['account_ids_by_evidence'].get(role) !=
            runs[1]['scope']['account_ids_by_evidence'].get(role)
            for role in ('holdings', 'activities', 'policy', 'snapshots_in_resolved_window'))
            or any(runs[0]['scope'][key] != runs[1]['scope'][key]
                   for key in ('has_unassigned_accounts_by_evidence', 'account_membership_at_bookends'))):
        reasons.append('account_scope_changed')
    if any(old.get(key) != new.get(key) for key in ('period_start', 'period_end')) or any(
            key in parameter_changes for key in ('since', 'until')):
        reasons.append('date_window_changed')
    if not all(result.get('period_start') and result.get('period_end') for result in (old, new)):
        reasons.append('date_window_unknown')
    if old.get('base_currency') != new.get('base_currency'):
        reasons.append('reporting_currency_changed')
    if method_changes or a['methods'] != b['methods']:
        reasons.append('method_or_semantics_changed')
    if environment_changes:
        reasons.append('recorded_environment_changed')
    if any(run['runtime_compatibility']['mismatches'] for run in runs):
        reasons.append('recorded_runtime_unsupported')
    if any(result.get('twr_method') not in ('modified_dietz', 'linked_subperiod', 'bookend_ratio', 'unavailable')
           or result.get('mwr_method') != 'xirr' for result in (old, new)):
        reasons.append('method_evidence_unsupported')
    comparable = not reasons
    deltas = {}
    if comparable:
        for metric in _METRICS:
            previous, current = old[metric], new[metric]
            available = previous is not None and current is not None
            # Incomplete financial evidence cannot be promoted to a numeric zero.
            available &= all(result.get('fx_status') in ('complete', 'legacy_approximate') and result.get('valuation_status')
                             in ('recorded_unverified', 'complete') for result in (old, new))
            if metric.endswith('_pct'):
                available &= all(result.get('return_convention') in ('total_return', 'price_return')
                                 for result in (old, new))
            difference = current - previous if available else None
            available &= difference is not None and math.isfinite(difference)
            deltas[metric] = {'before': previous, 'after': current,
                              'delta': difference if available else None,
                              'status': 'available' if available else 'unknown_or_unavailable',
                              'unit': 'percentage_points' if metric.endswith('_pct') else old['base_currency']}
    held_fixed = {'parameters': not parameter_changes, 'methods': not method_changes and a['methods'] == b['methods'],
                  'environment': not environment_changes, 'other_input_bytes': False}
    classification = 'unresolved'
    if not roles and not parameter_changes and not method_changes and not environment_changes and old == new:
        classification = 'unchanged'
    elif comparable and all(held_fixed[key] for key in ('parameters', 'methods', 'environment')):
        additions = activities['added']
        old_ids = {row['id'] for row in old_portfolio.get('activities', [])}
        if (roles == ['portfolio'] and sections == ['activities'] and len(additions) == 1
                and not activities['removed'] and not activities['modified']
                and all(row['correction'] and row['correction']['supersedes_activity_id'] in old_ids
                        for row in additions)):
            classification = 'controlled_source_correction'
            held_fixed['other_input_bytes'] = True
        elif (roles and set(roles) <= {'historical_fx', 'historical_fx.market_series_file'}
              and _controlled_fx_revision(a, b, a_bytes, b_bytes)):
            classification = 'controlled_fx_revision'
            held_fixed['other_input_bytes'] = True
    return {'format': 'rikdom-analysis-comparison', 'format_version': '1.0',
            'operation': 'performance', 'replayed': False,
            'before': runs[0], 'after': runs[1],
            'changes': {'files': files, 'input_roles': roles, 'input_mapping': mapping_changes, 'portfolio_sections': sections,
                        'activities': activities, 'parameters': parameter_changes,
                        'source_reviews': (old_portfolio.get('extensions', {}).get('rikdom_reviewed_imports') !=
                                           new_portfolio.get('extensions', {}).get('rikdom_reviewed_imports')),
                        'methods': method_changes, 'environment': environment_changes,
                        'valuations': [item for item in files if any(side and side['role'] in _VALUATION_ROLES
                                                                   for side in (item['before'], item['after']))],
                        'fx': [item for item in files if any(side and side['role'] in _FX_ROLES
                                                           for side in (item['before'], item['after']))]},
            'compatibility': {'comparable': comparable, 'reasons': reasons},
            'coverage': coverage, 'deltas': deltas,
            'explanation': {'classification': classification, 'held_fixed': held_fixed,
                            'causation': 'not_established_by_recorded_comparison',
                            'meaning': 'Isolation concerns captured inputs only. File differences do not prove why an answer changed. No replay, investment return, or residual decomposition is claimed.'}}

def cmd_compare_analysis(args: argparse.Namespace) -> int:
    """Print comparison JSON; never bootstrap or write a workspace."""
    try:
        result = compare_analysis_runs(args.before, args.after)
    except AnalysisRunError as exc:
        print(f'Analysis comparison failed: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0
