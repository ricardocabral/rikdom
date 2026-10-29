"""Replay full, explicit historical positions against local price/FX evidence.

``replay_historical_valuations`` validates a versioned evidence file and hides
quote selection, identity checks and fail-closed portfolio aggregation. It never
reads today's holdings, reconstructs quantities, acquires data or writes files.
Only unadjusted prices can value the explicitly asserted historical quantities.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from .historical_fx import HistoricalFx
from .market_series import (
    MarketSeries, _currency, _iso, _number, _object, _reject_constant, _text,
    _timestamp, _unique_object, load_market_series,
)


def _validate_snapshots(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError('snapshots must be a nonempty array of explicit full position evidence')
    snapshots: list[dict[str, Any]] = []
    times = set()
    for item in raw:
        row = _object(item, {'as_of', 'source', 'positions_complete', 'positions'}, 'snapshot')
        when = _timestamp(row['as_of'], 'snapshot.as_of')
        if when in times:
            raise ValueError('duplicate snapshot timestamp')
        times.add(when)
        _text(row['source'], 'snapshot.source')
        if not isinstance(row['positions_complete'], bool):
            raise ValueError('positions_complete must be a boolean assertion')
        if not isinstance(row['positions'], list):
            raise ValueError('positions must be an array')
        ids = set()
        for position in row['positions']:
            kind = position.get('kind') if isinstance(position, dict) else None
            fields = {'id', 'kind'}
            if kind == 'security':
                fields |= {'instrument', 'quantity', 'price_series_id'}
            elif kind == 'cash':
                fields |= {'currency', 'amount'}
            else:
                raise ValueError('position.kind must be security or cash')
            _object(position, fields, 'position')
            pid = _text(position['id'], 'position.id')
            if pid in ids:
                raise ValueError('duplicate position id within snapshot')
            ids.add(pid)
            if kind == 'security':
                identity = _object(position['instrument'], {'namespace', 'id', 'currency'}, 'instrument')
                _text(identity['namespace'], 'instrument.namespace')
                _text(identity['id'], 'instrument.id')
                _currency(identity['currency'])
                _number(position['quantity'], positive=False)
                _text(position['price_series_id'], 'price_series_id')
            else:
                _currency(position['currency'])
                _number(position['amount'], positive=False)
        snapshots.append({**copy.deepcopy(row), 'as_of': _iso(when)})
    return sorted(snapshots, key=lambda row: _timestamp(row['as_of'], 'as_of'))


def _value_position(
    position: dict[str, Any], snapshot: dict[str, Any], series: MarketSeries,
    fx: HistoricalFx, *, max_age: float, cutoff: str | None,
) -> dict[str, Any]:
    price = None
    native_value = None
    reason = None
    if position['kind'] == 'security':
        currency = position['instrument']['currency']
        price = series.lookup(
            position['price_series_id'], as_of=snapshot['as_of'],
            max_age_seconds=max_age, retrieved_before=cutoff,
        )
        metadata = price['series']
        if metadata is not None and (
            metadata['kind'] != 'price' or metadata.get('instrument') != position['instrument']
        ):
            reason = 'incompatible_instrument'
        elif metadata is not None and metadata['adjustment'] != 'unadjusted':
            reason = 'unsupported_price_adjustment'
        elif price['status'] != 'available':
            reason = price['reason']
        else:
            native_value = float(position['quantity']) * float(price['observation']['value'])
    else:
        currency = position['currency']
        native_value = float(position['amount'])
    rate = fx.resolve(currency, _timestamp(snapshot['as_of'], 'as_of'))
    diagnostics = [reason] if reason else []
    if rate.status != 'available':
        diagnostics.append(rate.reason)
    if native_value is not None and not math.isfinite(native_value):
        native_value = None
        diagnostics.append('nonfinite_native_value')
    base_value = None
    if not diagnostics:
        base_value = native_value * rate.rate
        if not math.isfinite(base_value):
            base_value = None
            diagnostics.append('nonfinite_base_value')
    return {
        'position': copy.deepcopy(position),
        'status': 'unavailable' if diagnostics else 'complete',
        'reason': diagnostics[0] if diagnostics else None,
        'diagnostics': diagnostics, 'native_value': native_value,
        'base_value': base_value, 'price': price, 'fx': rate.evidence,
    }


def replay_historical_valuations(path: str | Path, *, base_currency: str) -> dict[str, Any]:
    """Return schema-compatible snapshots only when every requested date is complete.

    Strict v1 config holds ``market_series_file``, ``price_max_age_seconds``,
    ``fx_max_age_seconds``, ``retrieved_before``, ``series_by_currency`` and
    ``snapshots``. Local paths resolve against the config directory. Malformed
    evidence raises ValueError; missing, stale or incompatible quotes retain all
    lookup evidence and make the result unavailable. Empty positions mean zero
    only with an explicit ``positions_complete: true`` assertion. The returned
    dictionaries are detached, with no timestamps from the current clock.
    """
    base_currency = _currency(base_currency)
    path = Path(path)
    with path.open(encoding='utf-8') as handle:
        config = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    _object(config, {'contract_version', 'market_series_file', 'price_max_age_seconds',
                     'fx_max_age_seconds', 'retrieved_before', 'series_by_currency',
                     'snapshots'}, 'historical valuation config')
    if config['contract_version'] != '1.0':
        raise ValueError("unsupported historical valuation contract_version; expected '1.0'")
    snapshots = _validate_snapshots(config['snapshots'])
    age = _number(config['price_max_age_seconds'], positive=False)
    cutoff = config['retrieved_before']
    if cutoff is not None:
        cutoff = _iso(_timestamp(cutoff, 'retrieved_before'))
    series_path = Path(_text(config['market_series_file'], 'market_series_file'))
    if not series_path.is_absolute():
        series_path = path.parent / series_path
    series = load_market_series(series_path)
    fx = HistoricalFx(
        series, base_currency=base_currency, series_by_currency=config['series_by_currency'],
        max_age_seconds=config['fx_max_age_seconds'], retrieved_before=cutoff,
    )
    valuations = []
    usable = []
    diagnostics = []
    for snapshot in snapshots:
        positions = [_value_position(position, snapshot, series, fx, max_age=age, cutoff=cutoff)
                     for position in snapshot['positions']]
        problems = []
        if not snapshot['positions_complete']:
            problems.append('positions_not_asserted_complete')
        for position in positions:
            problems.extend(f"{position['position']['id']}: {reason}"
                            for reason in position['diagnostics'])
        value = None
        if not problems:
            value = sum(position['base_value'] for position in positions)
            if not math.isfinite(value):
                value = None
                problems.append('nonfinite_portfolio_value')
        status = 'unavailable' if problems else 'complete'
        valuations.append({
            'as_of': snapshot['as_of'], 'source': snapshot['source'],
            'positions_complete': snapshot['positions_complete'], 'status': status,
            'portfolio_value_base': value, 'positions': positions, 'diagnostics': problems,
        })
        diagnostics.extend(f"{snapshot['as_of']}: {problem}" for problem in problems)
        if not problems:
            usable.append({
                'timestamp': snapshot['as_of'], 'base_currency': base_currency,
                'totals': {'portfolio_value_base': value, 'by_asset_class': {}},
                'metadata': {'historical_valuation': {
                    'source': snapshot['source'], 'convention': 'unadjusted_price',
                }},
            })
    return {
        'contract_version': '1.0', 'base_currency': base_currency,
        'status': 'unavailable' if diagnostics else 'complete',
        'snapshots': [] if diagnostics else usable,
        'valuations': valuations, 'diagnostics': diagnostics,
    }
