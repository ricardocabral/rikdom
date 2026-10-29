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


def _same_json(left: Any, right: Any) -> bool:
    """Compare JSON evidence without Python's True == 1 / False == 0 aliasing."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_json(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


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
    extensions = activity.get('extensions') or {}
    if not isinstance(extensions, dict):
        raise ValueError('Activity extensions must be an object')
    marker = extensions.get('rikdom_market_event', {})
    if not isinstance(marker, dict):
        raise ValueError('Market event evidence must be an object')
    return _json_copy(marker)


def _split_row(event: dict[str, Any], revision: dict[str, Any], review: dict[str, Any],
               marker: dict[str, Any], aid: str, target: str | None = None) -> dict[str, Any]:
    extensions = {'rikdom_market_event': marker}
    if target is not None:
        extensions['rikdom_correction'] = {
            'version': 1, 'supersedes_activity_id': target,
            'reason': f"Reviewed split revision evidence: {review['source']}"}
    return {'id': aid, 'idempotency_key': aid, 'status': 'posted',
            'source_system': 'rikdom-market-events', 'source_ref': review['source'],
            'event_type': 'split', 'effective_at': revision['effective_at'],
            'holding_id': review['holding_id'], 'account_id': review['account_id'],
            'instrument': copy.deepcopy(event['instrument']),
            'corporate_action': {'kind': 'split' if revision['ratio'] >= 1 else 'reverse_split',
                'exchange_ratio': revision['ratio'],
                'legs': [{'holding_id': review['holding_id'],
                          'quantity_delta': review['post_quantity'] - review['pre_quantity']}]},
            'extensions': copy.deepcopy(extensions)}


def _split_history(activities: dict[str, dict[str, Any]], event: dict[str, Any],
                   scope: list[str], known_sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    root = activities.get(_activity_id(event, scope))
    for row in activities.values():
        marker = _marker(row)
        if (marker.get('event_id') == event['id'] and row.get('holding_id') == scope[0]
                and row.get('account_id') == scope[1] and marker.get('instrument') != event['instrument']):
            return [], 'applied_revision_conflict'
    if root is None:
        return [], None
    successors = {link['supersedes_activity_id']: a for a in activities.values() if (link := correction(a))}
    history = []
    row = root
    while True:
        marker = _marker(row)
        announcement, reviewed = marker.get('announcement'), marker.get('review')
        if (not isinstance(announcement, dict) or not isinstance(reviewed, dict)
                or type(marker.get('version')) is not int or marker['version'] != 1
                or marker.get('event_id') != event['id']
                or marker.get('instrument') != event['instrument']
                or marker.get('revision_id') != announcement.get('id')
                or marker.get('source') != announcement.get('source')
                or marker.get('retrieved_at') != announcement.get('retrieved_at')):
            return [], 'applied_revision_conflict'
        source_event = marker.get('event')
        if (not isinstance(source_event, dict) or any(source_event.get(key) != event[key]
                for key in ('id', 'kind', 'instrument', 'adjustment_basis'))):
            return [], 'applied_revision_conflict'
        source_event = copy.deepcopy(source_event)
        source_chain = marker.get('source_chain')
        if source_chain is None:
            # Before revision support, initial application retained its exact
            # announcement but not its ancestors. Recover the validated prefix
            # from supplied evidence, never invent a missing source revision.
            source_chain = []
            for known in known_sources:
                source_chain.append(known)
                if known['id'] == announcement['id']:
                    if known != announcement:
                        return [], 'applied_revision_conflict'
                    break
            else:
                return [], 'stale_or_unrelated_revision'
        source_event['revisions'] = source_chain
        source = parse_market_events({'contract_version': '1.0', 'events': [source_event]})
        query = marker.get('query', {'as_of': announcement['effective_at'], 'retrieved_before': None})
        _object(query, {'as_of', 'retrieved_before'}, 'split query')
        selected = source.lookup(event['id'], **query)
        if selected['status'] != 'available' or selected['revision'] != announcement:
            return [], 'applied_revision_conflict'
        if (reviewed.get('reviewed') is not True or reviewed.get('revision_id') != announcement['id']
                or reviewed.get('holding_id') != scope[0] or reviewed.get('account_id') != scope[1]
                or reviewed.get('quantity_basis') != 'unadjusted'):
            return [], 'applied_revision_conflict'
        fields = {'contract_version', 'reviewed', 'revision_id', 'source', 'holding_id',
                  'account_id', 'quantity_basis', 'pre_quantity', 'post_quantity'}
        dated = reviewed.get('contract_version') == '1.1'
        if dated:
            fields |= {'effective_at', 'reviewed_at'}
        _object(reviewed, fields, 'stored split review')
        _text(reviewed['source'], 'stored review.source')
        if reviewed['contract_version'] not in ('1.0', '1.1') or (history and not dated):
            return [], 'applied_revision_conflict'
        if dated:
            when = _timestamp(reviewed['reviewed_at'], 'stored review.reviewed_at')
            if (_iso(_timestamp(reviewed['effective_at'], 'stored review.effective_at')) != announcement['effective_at']
                    or when < max(_timestamp(announcement['effective_at'], 'effective_at'),
                                  _timestamp(announcement['retrieved_at'], 'retrieved_at'))
                    or when > _timestamp(query['as_of'], 'stored query.as_of')):
                return [], 'applied_revision_conflict'
        pre = _number(reviewed.get('pre_quantity'), positive=True)
        post = _number(reviewed.get('post_quantity'), positive=True)
        if not math.isclose(pre * announcement['ratio'], post, rel_tol=1e-12, abs_tol=0):
            return [], 'applied_revision_conflict'
        expected_id = (_activity_id(event, [*scope, announcement['id']]) if history else _activity_id(event, scope))
        expected = _split_row(event, announcement, reviewed, marker, expected_id,
                              history[-1]['id'] if history else None)
        actual = {k: v for k, v in row.items() if k not in ('import_run_id', 'ingested_at')}
        if not _same_json(_json_copy(actual), expected):
            return [], 'applied_revision_conflict'
        if history:
            previous = _marker(history[-1])
            ancestors = {r['id']: r for r in selected['superseded']}
            for prior in previous.get('source_chain', [previous['announcement']]):
                if ancestors.get(prior['id']) != prior:
                    return [], 'applied_revision_conflict'
            if reviewed['pre_quantity'] != previous['review']['pre_quantity']:
                return [], 'applied_revision_conflict'
        history.append(row)
        if row['id'] not in successors:
            return history, None
        row = successors[row['id']]


def _split_dependencies(portfolio: dict[str, Any], history: list[dict[str, Any]],
                        scope: list[str], revision: dict[str, Any]) -> bool:
    """Conservative safe path: no affected lots or subsequent corporate actions.

    Plain trades remain recalculable from the effective ledger. Declared lots,
    explicit basis changes and later corporate actions need a separate audit,
    including dependencies retained anywhere in a related correction chain.
    """
    ids = {a['id'] for a in history}
    activities = portfolio.get('activities') or []
    # Holding IDs are globally unique. An activity's parent account cannot
    # exclude a direct or leg-scoped dependency on the revised holding.
    affected = {a['id'] for a in activities
                if a.get('holding_id') == scope[0]
                or any(leg.get('holding_id') == scope[0]
                       for leg in (a.get('corporate_action') or {}).get('legs', []))}
    # A correction can move scope or date. Follow both directions so neither a
    # retained ancestor nor a replacement can hide a lot/basis dependency.
    links = [(a['id'], link['supersedes_activity_id']) for a in activities if (link := correction(a))]
    while True:
        related = {endpoint for child, parent in links if child in affected or parent in affected
                   for endpoint in (child, parent)}
        if related <= affected:
            break
        affected.update(related)
    for lot in portfolio.get('tax_lots') or []:
        if (lot.get('holding_id') == scope[0]
                or lot.get('acquisition_activity_id') in ids | affected
                or lot.get('disposal_activity_id') in ids | affected):
            return True
    if any(a.get('tax_lot_ids') or any(leg.get('tax_lot_ids')
            for leg in (a.get('corporate_action') or {}).get('legs', [])) for a in history):
        return True
    earliest = min(_timestamp(revision['effective_at'], 'effective_at'),
                   *(_timestamp(a['effective_at'], 'effective_at') for a in history))
    for row in activities:
        if row.get('id') in ids or row.get('id') not in affected:
            continue
        action = row.get('corporate_action') or {}
        if (row.get('tax_lot_ids') or 'cost_basis_adjustment' in row
                or any(leg.get('tax_lot_ids') or 'cost_basis_delta' in leg
                       for leg in action.get('legs', []))):
            return True
        if row.get('status', 'posted') == 'cancelled':
            continue
        if ((action or row.get('event_type') in ('split', 'merger'))
                and _timestamp(row['effective_at'], 'effective_at') >= earliest):
            return True
    return False


def _preview_market_event(
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
    dated_split = event['kind'] == 'split' and review.get('contract_version') == '1.1'
    if dated_split:
        fields |= {'effective_at', 'reviewed_at'}
    _object(review, fields, 'review')
    if (review['contract_version'] not in (('1.0', '1.1') if event['kind'] == 'split' else ('1.0',))
            or not isinstance(review['reviewed'], bool)):
        raise ValueError('unsupported review contract_version or nonboolean reviewed')
    _text(review['revision_id'], 'review.revision_id')
    _text(review['source'], 'review.source')
    if not review['reviewed']:
        return unavailable('review_required')
    if dated_split:
        review['effective_at'] = _iso(_timestamp(review['effective_at'], 'review.effective_at'))
        review['reviewed_at'] = _iso(_timestamp(review['reviewed_at'], 'review.reviewed_at'))
        if review['effective_at'] != revision['effective_at']:
            return unavailable('review_effective_date_mismatch')
        reviewed_at = _timestamp(review['reviewed_at'], 'review.reviewed_at')
        if (reviewed_at < max(_timestamp(revision['effective_at'], 'effective_at'),
                              _timestamp(revision['retrieved_at'], 'retrieved_at'))
                or reviewed_at > _timestamp(as_of, 'as_of')):
            return unavailable('review_time_inconsistent')
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
    split_target = None
    if event['kind'] == 'split':
        # The root ID binds one source event to one holding/account. Revisions
        # receive their own identity and replace the current leaf in full.
        history, reason = _split_history(activities, event, scope, [*selection['superseded'], revision])
        if reason:
            return unavailable(reason)
        known = {r['id']: r for r in [*selection['superseded'], revision]}
        for row in history:
            applied = _marker(row)
            for source in applied.get('source_chain', [applied['announcement']]):
                if source['id'] in known and known[source['id']] != source:
                    return unavailable('applied_revision_conflict')
        for row in history:
            applied = _marker(row)
            if applied['revision_id'] == revision['id']:
                if applied['announcement'] != revision:
                    return unavailable('applied_revision_conflict')
                if applied['review'] != review:
                    return unavailable('applied_review_conflict')
                result.update(status='noop', reason='already_applied')
                return result
        if history:
            for row in history:
                applied = _marker(row)
                for source in applied.get('source_chain', [applied['announcement']]):
                    if source['id'] not in known:
                        return unavailable('stale_or_unrelated_revision')
                    if known[source['id']] != source:
                        return unavailable('applied_revision_conflict')
                if review['pre_quantity'] != applied['review']['pre_quantity']:
                    return unavailable('split_pre_quantity_changed')
            if not dated_split:
                return unavailable('split_revision_review_required')
            split_target = history[-1]
            if _timestamp(revision['retrieved_at'], 'retrieved_at') <= _timestamp(
                    _marker(split_target)['announcement']['retrieved_at'], 'retrieved_at'):
                return unavailable('stale_or_unrelated_revision')
            if _split_dependencies(portfolio, history, scope, revision):
                return unavailable('dependent_activity_review_required')
            aid = _activity_id(event, [*scope, revision['id']])
    existing = activities.get(aid)
    if existing is not None:
        marker = _marker(existing)
        if marker.get('review') == review and marker.get('revision_id') == revision['id']:
            if marker.get('announcement') != revision:
                return unavailable('applied_revision_conflict')
            result.update(status='noop', reason='already_applied')
            return result
        return unavailable('applied_review_conflict')
    if any(a.get('idempotency_key') == aid for a in activities.values()):
        return unavailable('activity_identity_collision')
    marker = {'version': 1, 'event_id': event_id, 'revision_id': revision['id'],
              'instrument': copy.deepcopy(identity), 'review': review,
              'source': revision['source'], 'retrieved_at': revision['retrieved_at'],
              'announcement': copy.deepcopy(revision), 'event': copy.deepcopy(event)}
    if event['kind'] == 'split':
        marker.update(source_chain=copy.deepcopy([*selection['superseded'], revision]),
                      query={'as_of': selection['as_of'], 'retrieved_before': selection['retrieved_before']})
        for recorded in effective_activities(list(activities.values())):
            if split_target is not None and recorded['id'] == split_target['id']:
                continue
            action = recorded.get('corporate_action') or {}
            is_split = (recorded.get('event_type') == 'split'
                        or action.get('kind') in ('split', 'reverse_split'))
            targets_holding = (recorded.get('holding_id') == holding_id
                               or any(leg.get('holding_id') == holding_id for leg in action.get('legs', [])))
            if (is_split and targets_holding and recorded.get('status', 'posted') != 'cancelled'
                    and _timestamp(recorded['effective_at'], 'effective_at') == _timestamp(revision['effective_at'], 'effective_at')):
                return unavailable('existing_split_requires_review')
        activity = _split_row(event, revision, review, marker, aid,
                              split_target['id'] if split_target is not None else None)
    else:
        successors = {link['supersedes_activity_id']: a for a in activities.values() if (link := correction(a))}
        ancestors = {row['id']: row for row in selection['superseded']}
        while True:
            applied = _marker(target)
            if applied.get('event_id') == event_id:
                previous = ancestors.get(applied.get('revision_id'))
                if previous is None:
                    return unavailable('stale_or_unrelated_revision')
                if applied.get('announcement') != previous:
                    return unavailable('applied_revision_conflict')
            if target['id'] not in successors:
                break
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
    result.update(status='ready', reason=None, activities=[activity])
    return result


def preview_market_event(
    portfolio: dict[str, Any], events: MarketEvents, *, event_id: str, as_of: str,
    review: dict[str, Any] | None = None, retrieved_before: str | None = None,
) -> EventPreview:
    """Recompute a detached proposal and validate it through the ledger merger."""
    result = _preview_market_event(portfolio, events, event_id=event_id, as_of=as_of,
                                   review=review, retrieved_before=retrieved_before)
    if result['status'] == 'ready':
        try:
            merge_activities(copy.deepcopy(portfolio), {'activities': result['activities']})
        except ValueError as exc:
            result.update(status='unavailable', activities=[], reason=(
                'dependent_activity_review_required' if 'dependent tax lots/corporate action' in str(exc)
                else 'activity_correction_rejected'))
    return result


def validate_reviewed_split_correction(portfolio: dict[str, Any], imported: dict[str, Any],
                                       activity: dict[str, Any]) -> None:
    """Allow only the exact recomputed reviewed split replacement, with no lots.

    Provenance is evidence, never an authorization flag. Reparse the retained
    source chain and recompute the entire proposal against the current ledger;
    no caller-supplied boolean can bypass correction or dependency integrity.
    """
    marker = _marker(activity)
    if not marker or not isinstance(marker.get('query'), dict):
        raise ValueError('Correction requires review of dependent tax lots/corporate action')
    event = copy.deepcopy(marker.get('event'))
    if not isinstance(event, dict) or event.get('kind') != 'split':
        raise ValueError('Reviewed split correction requires exact split source evidence')
    event['revisions'] = marker.get('source_chain')
    events = parse_market_events({'contract_version': '1.0', 'events': [event]})
    query = _object(marker['query'], {'as_of', 'retrieved_before'}, 'split query')
    context = copy.deepcopy(portfolio)
    context['tax_lots'] = [*(portfolio.get('tax_lots') or []), *(imported.get('tax_lots') or [])]
    # Other incoming rows could otherwise rewrite an ancestor after proof
    # validation. The normal workflow appends exactly one reviewed replacement.
    if len(imported.get('activities') or []) != 1:
        raise ValueError('Reviewed split correction requires a single activity import')
    result = _preview_market_event(context, events, event_id=marker.get('event_id'),
        as_of=query['as_of'], retrieved_before=query['retrieved_before'], review=marker.get('review'))
    normalized = {k: v for k, v in activity.items() if k not in ('import_run_id', 'ingested_at')}
    if result['status'] != 'ready' or not _same_json(result['activities'], [_json_copy(normalized)]):
        raise ValueError('Correction requires review of dependent tax lots/corporate action: '
                         + str(result['reason'] or 'reviewed split proof mismatch'))


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
