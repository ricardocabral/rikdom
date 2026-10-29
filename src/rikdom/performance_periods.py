"""Exact UTC calendar windows shared by the CLI and offline reports.

A row owns flows in (start, end]; its opening valuation is post-flow. Missing
calendar boundaries are never replaced with nearby snapshots. Returns and all
financial evidence come from the existing performance engine, not aggregation
of monthly percentages or annualized XIRRs.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from rfc3339_validator import validate_rfc3339

from .activities import effective_activities
from .benchmarks import BenchmarkLoader
from .historical_fx import HistoricalFx
from .performance import compute_performance, parse_flow_valuations
from .performance_report import performance_to_dict


def _instant(value: str | datetime) -> datetime:
    if isinstance(value, str) and not validate_rfc3339(value):
        raise ValueError('Calendar valuations require valid RFC3339 timestamps')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Calendar valuations require timestamps with explicit timezone')
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace('+00:00', 'Z')


def _bound(value: str | datetime | None, *, until: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str) and len(value) == 10:
        parsed = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return parsed + timedelta(days=1, microseconds=-1) if until else parsed
    return _instant(value)


def compute_calendar_performance(
    snapshots: list[dict[str, Any]], activities: list[dict[str, Any]], *, base_currency: str,
    since: str | datetime | None = None, until: str | datetime | None = None,
    fx_rates_to_base: dict[str, float] | None = None,
    historical_fx: HistoricalFx | None = None,
    flow_valuations: dict[str, Any] | None = None,
    valuation_replay: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None, benchmark_loader: BenchmarkLoader | None = None,
) -> dict[str, Any]:
    """Return monthly and yearly rows with explicit coverage and availability.

    Full rows require exact UTC month/year endpoints; partial bookends use the
    actual history or explicit requested endpoints and are labeled partial.
    Each row serializes the same calculator output as the selected CLI period.
    Reviewed profit lots are period-specific, so are not inferred for these rows.
    """
    output: dict[str, Any] = {
        'status': 'unavailable', 'scope': 'portfolio', 'timezone': 'UTC',
        'cashflow_interval': '(start,end]', 'opening_valuation': 'post_flow',
        'monthly': [], 'yearly': [], 'warnings': [],
    }
    if valuation_replay is not None:
        output['valuation_replay'] = deepcopy(valuation_replay)
        snapshots = valuation_replay['snapshots']
    by_time = {}
    try:
        if flow_valuations is not None:
            parse_flow_valuations(flow_valuations, base_currency)
            output['flow_valuations'] = deepcopy(flow_valuations)
        for snap in snapshots:
            timestamp = _instant(snap['timestamp'])
            if timestamp in by_time:
                raise ValueError('Duplicate calendar valuation timestamp')
            by_time[timestamp] = snap
        history_times = list(by_time)
        if valuation_replay is not None and not history_times:
            history_times = [_instant(row['as_of']) for row in valuation_replay['valuations']]
        start = _bound(since)
        end = _bound(until, until=True)
        if not history_times and (start is None or end is None):
            raise ValueError('No valid snapshot history available for calendar performance')
        start = start if start is not None else min(history_times)
        end = end if end is not None else max(history_times)
        if end <= start:
            raise ValueError('Calendar performance requires an end later than its start')
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        output['warnings'].append(str(exc))
        return output

    # Resolve ledger reversals before slicing. A correction outside a row can
    # change which original event is effective inside the row.
    ledger = effective_activities(activities)

    def row_for(left: datetime, right: datetime, label: str, complete: bool) -> dict[str, Any]:
        row = {'label': label, 'period_start': _iso(left), 'period_end': _iso(right),
               'coverage': 'complete' if complete else 'partial',
               'status': 'unavailable', 'performance': None, 'warnings': []}
        missing = [value for value in (left, right) if value not in by_time]
        if missing:
            row['warnings'].append('Missing exact calendar valuation at ' + ', '.join(_iso(value) for value in missing))
            return row
        if valuation_replay is not None and valuation_replay['status'] != 'complete':
            row['warnings'].append('Historical valuation unavailable; no recorded snapshot fallback was used')
            return row
        selected = []
        for activity in ledger:
            try:
                when = _instant(activity['effective_at'])
            except (ValueError, TypeError, KeyError, AttributeError):
                # Keep malformed events so the calculator discloses their lack
                # of trustworthy timing instead of hiding them during slicing.
                selected.append(activity)
                continue
            if left < when <= right:
                selected.append(activity)
        row_flow_valuations = None
        if flow_valuations is not None:
            row_flow_valuations = {**flow_valuations, 'valuations': [
                value for value in flow_valuations['valuations']
                if left < _instant(value['timestamp']) <= right
            ]}
        calculated = compute_performance(
            [by_time[left], by_time[right]], selected, base_currency=base_currency,
            fx_rates_to_base=fx_rates_to_base, historical_fx=historical_fx,
            flow_valuations=row_flow_valuations, policy=policy, benchmark_loader=benchmark_loader,
        )
        row['performance'] = performance_to_dict(
            calculated, historical_fx=historical_fx, valuation_replay=valuation_replay,
        )
        row['status'] = 'available' if calculated.twr_return_pct is not None else 'unavailable'
        return row

    for frequency in ('monthly', 'yearly'):
        cursor = start.replace(month=1 if frequency == 'yearly' else start.month,
                               day=1, hour=0, minute=0, second=0, microsecond=0)
        while cursor < end:
            following = (cursor.replace(year=cursor.year + 1, month=1) if frequency == 'yearly'
                         else cursor.replace(year=cursor.year + 1, month=1) if cursor.month == 12
                         else cursor.replace(month=cursor.month + 1))
            left, right = max(start, cursor), min(end, following)
            label = cursor.strftime('%Y' if frequency == 'yearly' else '%Y-%m')
            output[frequency].append(row_for(left, right, label, left == cursor and right == following))
            cursor = following
    states = [row['status'] == 'available' for key in ('monthly', 'yearly') for row in output[key]]
    output['status'] = 'available' if all(states) else 'partial' if any(states) else 'unavailable'
    return output
