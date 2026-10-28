"""Received dividend/interest accounting without FX or inferred tax linkage.

``build_income_report`` performs the income calculation; ``income_amount_basis``
shares source amount semantics with return calculations. It selects the effective
ledger before filtering and never mutates its input. All dimensions are asserted
on the event; current holdings are not used to invent historical attribution.
"""
from __future__ import annotations

import copy
from datetime import date, datetime
from decimal import Decimal
import json
import math
import re
from typing import Any

from .activities import check_financial_contract, effective_activities


_METRICS = ('gross', 'withholding', 'fees', 'net')
_DATE_CONVENTION = 'Calendar date in effective_at explicit offset; inclusive start/end; no UTC conversion.'
_LIMITATIONS = [
    'Only posted dividend and interest events in the effective ledger are received income.',
    'No FX conversion, separate tax-event linkage, announced-event forecast, or yield on cost.',
    'Missing withholding is unknown, not zero. Absent fees are unreported; only declared fees affect gross/net.',
    'References are asserted activity dimensions; missing attribution is null.',
]


def _bound(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f'{name} must be an ISO date (YYYY-MM-DD)')
    date.fromisoformat(value)
    return value


def _event_date(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value
    ):
        raise ValueError('effective_at must be a timestamp with an explicit offset')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.date().isoformat()


def _money(value: Any) -> tuple[Decimal, str]:
    if not isinstance(value, dict):
        raise ValueError('Missing or malformed money')
    amount, currency = value.get('amount'), value.get('currency')
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or (isinstance(amount, float) and not math.isfinite(amount)):
        raise ValueError('Money amount must be a finite number, not a boolean')
    if not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
        raise ValueError('Money currency must be a three-letter uppercase code')
    return Decimal(str(amount)), currency


def _json_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Income amount exceeds finite JSON number range')
    return number


def income_amount_basis(activity: dict[str, Any]) -> str:
    """Return gross/net/unknown, validating an explicit v1 income marker.

    Unmarked money follows the schema's gross convention. Legacy canonical
    ``metadata.amount_basis=reported_gross_net_unknown`` preserves uncertainty.
    A modern rikdom_income marker takes precedence over that legacy marker.
    """
    metadata = activity.get('metadata', {})
    if not isinstance(metadata, dict):
        raise ValueError('Activity metadata must be an object')
    if 'rikdom_income' not in metadata:
        return 'unknown' if metadata.get('amount_basis') == 'reported_gross_net_unknown' else 'gross'
    marker = metadata['rikdom_income']
    if (not isinstance(marker, dict) or type(marker.get('version')) is not int
            or marker['version'] != 1 or marker.get('amount_basis') not in ('gross', 'net', 'unknown')):
        raise ValueError('metadata.rikdom_income requires version 1 and amount_basis gross, net, or unknown')
    return marker['amount_basis']


def _event_row(activity: dict[str, Any]) -> dict[str, Any]:
    amount, currency = _money(activity.get('money'))
    basis = income_amount_basis(activity)
    diagnostics = []
    charges = {}
    cross_currency = False
    for field, metric in (('withholding_tax', 'withholding'), ('fees', 'fees')):
        charges[metric] = None
        if field not in activity:
            continue
        charge, code = _money(activity[field])
        if code != currency:
            cross_currency = True
            diagnostics.append(f'{field} currency {code} differs from income currency {currency}; amount unavailable without FX.')
        else:
            charges[metric] = charge
    tax, fee = charges['withholding'], charges['fees']
    gross = amount if basis == 'gross' else None
    net = amount if basis == 'net' else None
    if basis == 'unknown':
        diagnostics.append('Unknown amount basis; gross and net unavailable.')
    elif tax is None:
        diagnostics.append('Withholding unavailable; cannot derive ' + ('net.' if basis == 'gross' else 'gross.'))
    elif not cross_currency:
        if basis == 'gross':
            net = amount - tax - (fee if fee is not None else Decimal(0))
        else:
            gross = amount + tax + (fee if fee is not None else Decimal(0))
    row = {
        'activity_id': activity.get('id'), 'event_type': activity['event_type'],
        'date': _event_date(activity.get('effective_at')), 'currency': currency,
        'amount_basis': basis, 'gross': gross, 'net': net, **charges,
        'diagnostics': diagnostics,
    }
    for field in ('account_id', 'asset_type_id', 'holding_id', 'instrument'):
        value = activity.get(field)
        if value is not None and not isinstance(value, dict if field == 'instrument' else str):
            raise ValueError(f'Invalid activity {field}')
        row[field] = copy.deepcopy(value)
    # Instruments are open source metadata but must still be JSON-safe.
    json.dumps(row['instrument'], allow_nan=False)
    return row


def _buckets(rows: list[dict[str, Any]], length: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row['date'][:length], row['currency']), []).append(row)
    buckets = []
    for (period, currency), events in sorted(grouped.items()):
        bucket = {'period': period, 'currency': currency, 'event_count': len(events)}
        for metric in _METRICS:
            unavailable = sum(row[metric] is None for row in events)
            subtotal = _json_number(sum((row[metric] for row in events if row[metric] is not None), Decimal(0)))
            bucket[metric] = {'total': None if unavailable else subtotal,
                              'known_subtotal': subtotal, 'unavailable_count': unavailable}
        buckets.append(bucket)
    return buckets


def build_income_report(
    portfolio: dict[str, Any], *, start: str | None = None, end: str | None = None,
) -> dict[str, Any]:
    """Build deterministic, JSON-safe received-income rows and native buckets.

    ``start`` and ``end`` are inclusive YYYY-MM-DD bounds on the calendar day
    at each event's explicit offset. Invalid contracts, retained income amounts,
    dates, or basis markers raise ValueError. Corrections are selected first.

    Event gross/net/withholding/fees are signed native-currency numbers or null
    when unavailable. Absent money basis means gross (schema convention).
    Missing tax prevents derivation; absent fees are unreported, and only
    declared fees enter derivation. Cross-currency charges are unavailable and
    prevent derivation. Explicit net money remains known despite unknown tax.

    Each monthly/yearly metric has ``known_subtotal`` (sum of available event
    values), ``unavailable_count``, and ``total`` (null unless every event value
    is known). Subtotals are never represented as complete totals. Only event
    dimensions are copied; missing historical attribution stays null.
    """
    if not isinstance(portfolio, dict):
        raise ValueError('Portfolio must be an object')
    activities = portfolio.get('activities', [])
    if not isinstance(activities, list) or any(not isinstance(a, dict) for a in activities):
        raise ValueError('Activities must be a list of activity objects')
    identities: set[str] = set()
    keys: set[str] = set()
    for activity in activities:
        identity = activity.get('id')
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise ValueError('Income ledger requires unique nonempty activity IDs')
        identities.add(identity)
        if activity.get('status') not in ('posted', 'pending', 'cancelled'):
            raise ValueError(f'Activity {identity!r} requires an explicit valid status')
        key = activity.get('idempotency_key')
        if key is not None:
            if not isinstance(key, str) or not key.strip() or key in keys:
                raise ValueError('Income ledger requires unique nonempty idempotency keys')
            keys.add(key)
    check_financial_contract(portfolio)
    start, end = _bound(start, 'start'), _bound(end, 'end')
    if start and end and start > end:
        raise ValueError('start must be on or before end')
    rows = []
    excluded_generic = 0
    for activity in effective_activities(portfolio.get('activities') or []):
        if activity['status'] != 'posted':
            continue
        if activity.get('event_type') == 'income':
            excluded_generic += 1
        if activity.get('event_type') not in ('dividend', 'interest'):
            continue
        try:
            day = _event_date(activity.get('effective_at'))
            if (start and day < start) or (end and day > end):
                continue
            rows.append(_event_row(activity))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Income activity {activity.get('id')!r}: {exc}") from exc
    rows.sort(key=lambda row: (row['date'], str(row['activity_id'])))
    monthly, yearly = _buckets(rows, 7), _buckets(rows, 4)
    diagnostics = [{'activity_id': row['activity_id'], 'message': message}
                   for row in rows for message in row['diagnostics']]
    if excluded_generic:
        diagnostics.append({'activity_id': None, 'message':
                            f'{excluded_generic} posted generic income event(s) excluded across effective history; no dividend/interest classification asserted.'})
    for row in rows:
        for metric in _METRICS:
            row[metric] = _json_number(row[metric])
    return {'version': 1, 'date_convention': _DATE_CONVENTION,
            'start': start, 'end': end, 'limitations': list(_LIMITATIONS),
            'diagnostics': diagnostics, 'events': rows, 'monthly': monthly, 'yearly': yearly}
