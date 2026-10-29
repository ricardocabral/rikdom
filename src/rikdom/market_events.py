"""Versioned local announcements and reviewed, append-only ledger proposals.

Load/parse validates complete files. Lookup separates effective time from the
inclusive retrieval cutoff. Preview never mutates its inputs. Apply recomputes a
preview and returns a detached portfolio through the existing activity merger;
the caller owns persistence. Neither announcements nor current holdings establish
entitlement, cash availability, payment confirmation, or historical positions.
No quote is accepted, adjusted, or rewritten by this module.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal, TypedDict

from .activities import check_financial_contract, correction, effective_activities
from .market_series import (
    _currency, _iso, _number, _object, _reject_constant, _text, _timestamp,
    _unique_object,
)
from .plugins import merge_activities


class EventLookup(TypedDict):
    status: Literal['available', 'missing']
    reason: str | None
    event_id: str
    as_of: str
    retrieved_before: str | None
    event: dict[str, Any] | None
    revision: dict[str, Any] | None
    superseded: list[dict[str, Any]]


class EventPreview(TypedDict):
    status: Literal['ready', 'unavailable', 'noop']
    reason: str | None
    selection: EventLookup
    activities: list[dict[str, Any]]


def _money(value: Any, currency: str) -> dict[str, Any]:
    row = _object(value, {'amount', 'currency'}, 'money')
    _number(row['amount'], positive=False)
    if _currency(row['currency']) != currency:
        raise ValueError('money currency must match instrument currency')
    return copy.deepcopy(row)


def _json_copy(value: Any) -> Any:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('JSON object keys must be strings')
        return {key: _json_copy(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_copy(child) for child in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError('Expected finite JSON data without coercions')


class MarketEvents:
    """Validated detached event store; construct with load/parse_market_events."""

    def __init__(self, events: dict[str, dict[str, Any]]):
        self._events = copy.deepcopy(events)

    def lookup(self, event_id: str, *, as_of: str,
               retrieved_before: str | None = None) -> EventLookup:
        """Select the latest known revision, then check effective time/coverage.

        Omitting retrieval cutoff uses every vintage in the file. A revised date
        in the future never falls back to a superseded, earlier effective date.
        Coverage describes supplied evidence, not complete market calendars.
        """
        _text(event_id, 'event_id')
        when = _timestamp(as_of, 'as_of')
        cutoff = _timestamp(retrieved_before, 'retrieved_before') if retrieved_before is not None else None
        event = self._events.get(event_id)
        result: EventLookup = {
            'status': 'missing', 'reason': 'unknown_event', 'event_id': event_id,
            'as_of': _iso(when), 'retrieved_before': _iso(cutoff) if cutoff else None,
            'event': None, 'revision': None, 'superseded': [],
        }
        if event is None:
            return result
        result['event'] = copy.deepcopy({k: v for k, v in event.items() if k != 'revisions'})
        if not (_timestamp(event['coverage']['start'], 'start') <= when
                <= _timestamp(event['coverage']['end'], 'end')):
            result['reason'] = 'outside_declared_coverage'
            return result
        known = [r for r in event['revisions']
                 if cutoff is None or _timestamp(r['retrieved_at'], 'retrieved_at') <= cutoff]
        if not known:
            result['reason'] = 'no_known_revision'
            return result
        result['revision'] = copy.deepcopy(known[-1])
        result['superseded'] = copy.deepcopy(known[:-1])
        if _timestamp(known[-1]['effective_at'], 'effective_at') > when:
            result['reason'] = 'event_not_effective'
            return result
        result.update(status='available', reason=None)
        return result


def parse_market_events(document: Any) -> MarketEvents:
    """Validate strict version 1.0 JSON, including single-root revision chains.

    Retrieval may precede effective time: these are announcements. Revisions may
    change dates but must have strictly later retrieval times and one successor.
    Per-unit null means unknown; zero is an explicit zero. IDs are stable source
    identities, never inferred from tickers, amounts, or nearby dates.
    """
    document = _object(_json_copy(document), {'contract_version', 'events'}, 'document')
    if document['contract_version'] != '1.0':
        raise ValueError("unsupported market events contract_version; expected '1.0'")
    if not isinstance(document['events'], list):
        raise ValueError('events must be an array')
    events: dict[str, dict[str, Any]] = {}
    revision_ids: set[str] = set()
    for event in document['events']:
        _object(event, {'id', 'kind', 'instrument', 'adjustment_basis', 'coverage', 'license', 'revisions'}, 'event')
        eid = _text(event['id'], 'event.id')
        if eid in events:
            raise ValueError('duplicate event id')
        kind = event['kind']
        if kind not in ('split', 'distribution'):
            raise ValueError('event.kind must be split or distribution')
        identity = _object(event['instrument'], {'namespace', 'id', 'currency'}, 'instrument')
        _text(identity['namespace'], 'instrument.namespace')
        _text(identity['id'], 'instrument.id')
        currency = _currency(identity['currency'])
        if event['adjustment_basis'] not in ('unadjusted', 'split_adjusted', 'total_return_adjusted'):
            raise ValueError('Unknown adjustment_basis')
        coverage = _object(event['coverage'], {'start', 'end'}, 'coverage')
        start, end = (_timestamp(coverage[key], f'coverage.{key}') for key in ('start', 'end'))
        if start > end:
            raise ValueError('coverage.start must not exceed coverage.end')
        event['coverage'] = {'start': _iso(start), 'end': _iso(end)}
        license_info = _object(event['license'], {'name', 'uri'}, 'license')
        _text(license_info['name'], 'license.name')
        _text(license_info['uri'], 'license.uri')
        revisions = event['revisions']
        if not isinstance(revisions, list) or not revisions:
            raise ValueError('revisions must be a nonempty array')
        by_id = {}
        for row in revisions:
            fields = {'id', 'effective_at', 'retrieved_at', 'source', 'supersedes'}
            fields |= {'ratio'} if kind == 'split' else {'per_unit', 'record_at', 'payment_at'}
            _object(row, fields, 'revision')
            rid = _text(row['id'], 'revision.id')
            if rid in revision_ids:
                raise ValueError('duplicate revision id')
            revision_ids.add(rid)
            effective = _timestamp(row['effective_at'], 'effective_at')
            retrieved = _timestamp(row['retrieved_at'], 'retrieved_at')
            if not start <= effective <= end:
                raise ValueError('revision effective_at must fall within coverage')
            row.update(effective_at=_iso(effective), retrieved_at=_iso(retrieved))
            _text(row['source'], 'source')
            if row['supersedes'] is not None:
                _text(row['supersedes'], 'supersedes')
            if kind == 'split':
                _number(row['ratio'], positive=True)
            else:
                if row['per_unit'] is not None:
                    _money(row['per_unit'], currency)
                for key in ('record_at', 'payment_at'):
                    if row[key] is not None:
                        row[key] = _iso(_timestamp(row[key], key))
            by_id[rid] = row
        roots = [row for row in revisions if row['supersedes'] is None]
        superseded: set[str] = set()
        for row in revisions:
            previous = row['supersedes']
            if previous is None:
                continue
            parent = by_id.get(previous)
            if (parent is None or previous in superseded
                    or _timestamp(parent['retrieved_at'], 'retrieved_at') >= _timestamp(row['retrieved_at'], 'retrieved_at')):
                raise ValueError('revisions require one strictly later retrieval chain within an event')
            superseded.add(previous)
        if len(roots) != 1:
            raise ValueError('event requires exactly one revision root')
        event['revisions'] = sorted(revisions, key=lambda row: _timestamp(row['retrieved_at'], 'retrieved_at'))
        events[eid] = event
    return MarketEvents(events)


def load_market_events(path: str | Path) -> MarketEvents:
    """Read one local JSON file; reject duplicate keys and nonfinite numbers."""
    with Path(path).open(encoding='utf-8') as handle:
        document = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    return parse_market_events(document)


def _indexed_rows(portfolio: dict[str, Any], field: str) -> dict[str, dict[str, Any]]:
    rows = portfolio.get(field, [])
    if not isinstance(rows, list):
        raise ValueError(f'{field} must be an array')
    index = {}
    keys = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f'{field} entries must be objects')
        rid = _text(row.get('id'), f'{field}.id')
        if rid in index:
            raise ValueError(f'duplicate {field} id')
        if field == 'activities' and row.get('idempotency_key') is not None:
            key = _text(row['idempotency_key'], 'idempotency_key')
            if key in keys:
                raise ValueError('duplicate activity idempotency_key')
            keys.add(key)
        index[rid] = row
    return index


def _identity_matches(row: dict[str, Any], identity: dict[str, Any]) -> bool:
    instrument = row.get('instrument')
    return isinstance(instrument, dict) and all(instrument.get(k) == v for k, v in identity.items())


def _activity_id(event: dict[str, Any], scope: list[str]) -> str:
    seed = json.dumps([event['id'], event['instrument'], *scope], sort_keys=True, separators=(',', ':'))
    return 'market-event:' + hashlib.sha256(seed.encode()).hexdigest()


def _marker(activity: dict[str, Any]) -> dict[str, Any]:
    return (activity.get('extensions') or {}).get('rikdom_market_event', {})


def preview_market_event(
    portfolio: dict[str, Any], events: MarketEvents, *, event_id: str, as_of: str,
    review: dict[str, Any] | None = None, retrieved_before: str | None = None,
) -> EventPreview:
    """Return ready/unavailable/noop plus detached activities and source evidence.

    Split reviews assert pre/post raw quantities for exactly one bound holding
    and account. Distribution reviews correct an explicitly referenced observed
    posted dividend/interest; reviewed money is never computed from per-unit
    amounts. Both paths require schema 2.0.0 and preserve holdings and tax lots.
    Missing evidence returns an actionable reason; malformed data raises ValueError.
    """
    selection = events.lookup(event_id, as_of=as_of, retrieved_before=retrieved_before)
    result: EventPreview = {'status': 'unavailable', 'reason': selection['reason'],
                            'selection': selection, 'activities': []}

    def unavailable(reason: str) -> EventPreview:
        result['reason'] = reason
        return result

    holdings = _indexed_rows(portfolio, 'holdings')
    activities = _indexed_rows(portfolio, 'activities')
    effective_activities(list(activities.values()))
    if selection['status'] != 'available':
        return result
    event, revision = selection['event'], selection['revision']
    if review is None:
        return unavailable('review_required')
    review = _json_copy(review)
    common = {'contract_version', 'reviewed', 'revision_id', 'source'}
    fields = (common | {'holding_id', 'account_id', 'quantity_basis', 'pre_quantity', 'post_quantity'}
              if event['kind'] == 'split' else
              common | {'observed_activity_id', 'money', 'amount_basis'})
    _object(review, fields, 'review')
    if review['contract_version'] != '1.0' or not isinstance(review['reviewed'], bool):
        raise ValueError('review requires contract_version 1.0 and boolean reviewed')
    _text(review['revision_id'], 'review.revision_id')
    _text(review['source'], 'review.source')
    if not review['reviewed']:
        return unavailable('review_required')
    if review['revision_id'] != revision['id']:
        return unavailable('review_revision_mismatch')
    if event['adjustment_basis'] != 'unadjusted':
        return unavailable('unsupported_adjustment_basis')
    if portfolio.get('schema_version') != '2.0.0':
        return unavailable('schema_upgrade_required')
    check_financial_contract(portfolio)
    identity = event['instrument']
    target = None
    if event['kind'] == 'split':
        holding_id = _text(review['holding_id'], 'holding_id')
        account_id = _text(review['account_id'], 'account_id')
        if review['quantity_basis'] != 'unadjusted':
            return unavailable('unsupported_quantity_basis')
        pre = _number(review['pre_quantity'], positive=False)
        post = _number(review['post_quantity'], positive=False)
        if pre == 0:
            return unavailable('no_position_evidence')
        expected = pre * revision['ratio']
        if expected <= 0 or not math.isfinite(expected) or not math.isclose(expected, post, rel_tol=1e-12, abs_tol=0):
            return unavailable('split_quantity_mismatch')
        if not math.isfinite(post - pre):
            return unavailable('nonfinite_quantity_delta')
        scope = [holding_id, account_id]
    else:
        observed_id = _text(review['observed_activity_id'], 'observed_activity_id')
        target = activities.get(observed_id)
        if target is None:
            return unavailable('observed_payment_not_found')
        # A link to a correction still resolves the same economic payment root.
        while (link := correction(target)) is not None:
            target = activities[link['supersedes_activity_id']]
        review['observed_activity_id'] = target['id']
        root_id = target['id']
        scope = [root_id, revision['id']]
        holding_id, account_id = target.get('holding_id'), target.get('account_id')
        if target.get('status') != 'posted' or target.get('event_type') not in ('dividend', 'interest'):
            return unavailable('observed_payment_not_posted')
        if not _identity_matches(target, identity):
            return unavailable('instrument_mismatch')
        if not isinstance(account_id, str) or not account_id:
            return unavailable('account_mismatch')
        if not target.get('source_ref') and not target.get('source_system'):
            return unavailable('observed_payment_source_required')
        if _timestamp(target['effective_at'], 'observed effective_at') > _timestamp(as_of, 'as_of'):
            return unavailable('observed_payment_not_effective')
        _money(target.get('money'), identity['currency'])
        _money(review['money'], identity['currency'])
        if review['amount_basis'] not in ('gross', 'net', 'unknown'):
            raise ValueError('review.amount_basis must be gross, net or unknown')
    holding = holdings.get(holding_id)
    if holding is None:
        return unavailable('holding_not_found')
    if not _identity_matches(holding, identity):
        return unavailable('instrument_mismatch')
    if holding.get('account_id') != account_id:
        return unavailable('account_mismatch')
    aid = _activity_id(event, scope)
    existing = activities.get(aid)
    if existing is not None:
        marker = _marker(existing)
        if marker.get('review') == review and marker.get('revision_id') == revision['id']:
            if marker.get('announcement') != revision:
                return unavailable('applied_revision_conflict')
            result.update(status='noop', reason='already_applied')
            return result
        reason = ('split_revision_requires_manual_correction' if event['kind'] == 'split'
                  and marker.get('revision_id') != revision['id'] else 'applied_review_conflict')
        return unavailable(reason)
    if any(a.get('idempotency_key') == aid for a in activities.values()):
        return unavailable('activity_identity_collision')
    marker = {'version': 1, 'event_id': event_id, 'revision_id': revision['id'],
              'instrument': copy.deepcopy(identity), 'review': review,
              'source': revision['source'], 'retrieved_at': revision['retrieved_at'],
              'announcement': copy.deepcopy(revision), 'event': copy.deepcopy(event)}
    if event['kind'] == 'split':
        for recorded in effective_activities(list(activities.values())):
            action = recorded.get('corporate_action') or {}
            is_split = (recorded.get('event_type') == 'split'
                        or action.get('kind') in ('split', 'reverse_split'))
            targets_holding = (recorded.get('holding_id') == holding_id
                               or any(leg.get('holding_id') == holding_id for leg in action.get('legs', [])))
            if (is_split and targets_holding and recorded.get('status', 'posted') != 'cancelled'
                    and _timestamp(recorded['effective_at'], 'effective_at') == _timestamp(revision['effective_at'], 'effective_at')):
                return unavailable('existing_split_requires_review')
        activity = {'event_type': 'split', 'effective_at': revision['effective_at'],
                    'holding_id': holding_id, 'account_id': account_id,
                    'instrument': copy.deepcopy(identity),
                    'corporate_action': {'kind': 'split' if revision['ratio'] >= 1 else 'reverse_split',
                                         'exchange_ratio': revision['ratio'],
                                         'legs': [{'holding_id': holding_id, 'quantity_delta': post - pre}]},
                    'extensions': {'rikdom_market_event': marker}}
    else:
        successors = {link['supersedes_activity_id']: a for a in activities.values() if (link := correction(a))}
        while target['id'] in successors:
            target = successors[target['id']]
        if target.get('status') != 'posted' or target.get('event_type') not in ('dividend', 'interest'):
            return unavailable('observed_payment_not_posted')
        if (not _identity_matches(target, identity) or target.get('holding_id') != holding_id
                or target.get('account_id') != account_id):
            return unavailable('observed_payment_identity_changed')
        if _timestamp(target['effective_at'], 'effective_at') > _timestamp(as_of, 'as_of'):
            return unavailable('observed_payment_not_effective')
        _money(target.get('money'), identity['currency'])
        activity = copy.deepcopy(target)
        for field in ('import_run_id', 'ingested_at', 'created_at'):
            activity.pop(field, None)
        activity['money'] = copy.deepcopy(review['money'])
        activity.setdefault('metadata', {})['rikdom_income'] = {'version': 1, 'amount_basis': review['amount_basis']}
        activity.setdefault('extensions', {}).update(
            rikdom_market_event=marker,
            rikdom_correction={'version': 1, 'supersedes_activity_id': target['id'],
                              'reason': f"Reviewed distribution evidence: {review['source']}"})
    activity.update(id=aid, idempotency_key=aid, status='posted',
                    source_system='rikdom-market-events', source_ref=review['source'])
    try:
        merge_activities(copy.deepcopy(portfolio), {'activities': [activity]})
    except ValueError as exc:
        return unavailable('dependent_activity_review_required' if 'dependent tax lots/corporate action' in str(exc)
                           else 'activity_correction_rejected')
    result.update(status='ready', reason=None, activities=[activity])
    return result


def apply_market_event(
    portfolio: dict[str, Any], events: MarketEvents, *, event_id: str, as_of: str,
    review: dict[str, Any], retrieved_before: str | None = None,
) -> tuple[dict[str, Any], EventPreview]:
    """Recompute the proposal and return (detached candidate portfolio, preview).

    Refuse unavailable proposals. Noop replay preserves every stored event,
    including an older revision replay after a newer payment correction. Never
    persist this result without the host's normal validation and atomic writer.
    """
    result = preview_market_event(portfolio, events, event_id=event_id, as_of=as_of,
                                  review=review, retrieved_before=retrieved_before)
    if result['status'] == 'unavailable':
        raise ValueError(f"Market event cannot be applied: {result['reason']}")
    candidate = copy.deepcopy(portfolio)
    if result['status'] == 'ready':
        candidate, _ = merge_activities(candidate, {'activities': result['activities']})
        check_financial_contract(candidate)
    return candidate, result
