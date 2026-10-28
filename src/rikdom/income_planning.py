"""Evidence-backed income planning, separate from the effective received ledger.

The single public calculation hides revision selection, explicit correction-aware
links, and conservative declared-cost yield. No holdings, ledger, FX, or provider
state is created or updated. See docs/reference/income-plan.md for the contract.
"""
from __future__ import annotations

import copy
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .activities import correction, effective_activities
from .income import _bound, _event_date, _json_number


_COST_EVENTS = {'buy', 'sell', 'transfer_in', 'transfer_out', 'split', 'reverse_split',
                'merger', 'spinoff', 'return_of_capital', 'amortization', 'corporate_action',
                'cost_basis_adjustment', 'reinvestment'}


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(files('rikdom._resources').joinpath('income-plan.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_plan(plan: Any) -> None:
    try:
        json.dumps(plan, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError('Income plan must contain finite JSON values') from exc
    errors = sorted(_validator().iter_errors(plan), key=lambda error: str(list(error.absolute_path)))
    if errors:
        first = errors[0]
        path = '/'.join(map(str, first.absolute_path)) or '<root>'
        raise ValueError(f'Income plan {path}: {first.message}')
    for row in plan.get('cost_bases', []):
        if row['period']['start'] > row['period']['end']:
            raise ValueError(f"Income plan cost basis {row['id']!r}: period start must precede end")
    for row in plan.get('announcements', []):
        if 'entitlement_quantity' in row and row['amount_kind'] != 'per_unit':
            raise ValueError('Entitlement quantity is only valid for per_unit announcements')


def _unique(rows: list[dict[str, Any]], *, revisions: bool = False) -> list[dict[str, Any]]:
    """Deduplicate refreshes, rejecting ambiguous identity/revision assignments."""
    seen = {}
    latest = {}
    for row in rows:
        key = (row['id'], row['revision']) if revisions else row['id']
        if key in seen and seen[key] != row:
            raise ValueError(f'Conflicting income plan identity/revision {key!r}')
        seen[key] = row
        if row['id'] not in latest or (revisions and row['revision'] > latest[row['id']]['revision']):
            latest[row['id']] = row
    return [copy.deepcopy(latest[key]) for key in sorted(latest)]


def _activity_source(activity: dict[str, Any]) -> str | None:
    provenance = activity.get('provenance') or {}
    if not isinstance(provenance, dict):
        return None
    direct, nested = activity.get('source_system'), provenance.get('source_system')
    if direct is not None and nested is not None and direct != nested:
        return None
    value = direct if direct is not None else nested
    return value if isinstance(value, str) and value.strip() else None


def _scope_relation(activity: dict[str, Any], scope: dict[str, Any]) -> bool | None:
    """Return unknown if missing historical dimensions could change membership."""
    missing = False
    for field, value in scope.items():
        actual = (_activity_source(activity)
                  if field == 'source_system' else activity.get(field))
        if actual is None:
            missing = True
        elif actual != value:
            return False
    return None if missing else True


def _inside(day: str, start: str | None, end: str | None) -> bool:
    return not ((start and day < start) or (end and day > end))


def _received(portfolio: dict[str, Any], report: dict[str, Any], start: str | None, end: str | None) -> dict[str, Any]:
    # Use the received engine's canonical semantics without invoking an embedded
    # plan recursively. Only the local extensions mapping is copied and changed.
    from .income import build_income_report

    unplanned = dict(portfolio)
    extensions = dict(portfolio.get('extensions') or {})
    extensions.pop('rikdom_income_plan', None)
    unplanned['extensions'] = extensions
    selected = build_income_report(unplanned, start=start, end=end)
    if not isinstance(report, dict) or report.get('version') != 1 or report.get('events') != selected['events']:
        raise ValueError('The received report must contain the canonical received events for this portfolio and period')
    return selected if not (start or end) else build_income_report(unplanned)


def _links(portfolio: dict[str, Any], announcements: list[dict[str, Any]], links: list[dict[str, Any]],
           received: dict[str, Any], start: str | None, end: str | None,
           diagnostics: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    original = {a['id']: a for a in portfolio.get('activities', [])}
    effective = {a['id']: a for a in effective_activities(portfolio.get('activities', []))}
    successors = {c['supersedes_activity_id']: a['id'] for a in original.values() if (c := correction(a))}
    by_announcement = {a['id']: a for a in announcements}
    rows = {a['activity_id']: a for a in received['events']}
    assigned = {}
    matched: dict[str, list[dict[str, Any]]] = {}
    outside = set()
    for link in sorted(links, key=lambda row: (row['announcement_id'], row['activity_id'])):
        aid, ann_id = link['activity_id'], link['announcement_id']
        if aid not in original or ann_id not in by_announcement:
            raise ValueError('Payment link references an unknown activity or announcement identity')
        while aid in successors:
            aid = successors[aid]
        if aid in assigned:
            if assigned[aid] != ann_id:
                raise ValueError(f'Effective payment {aid!r} is assigned to multiple announcements')
            continue
        assigned[aid] = ann_id
        activity, ann = effective[aid], by_announcement[ann_id]
        if ann['status'] == 'cancelled':
            diagnostics.append({'id': ann_id, 'message': f'Latest announcement is cancelled; linked activity {aid!r} excluded from entitlement comparison. Actual received income is unchanged.'})
            continue
        if activity['status'] != 'posted':
            diagnostics.append({'id': ann_id, 'message': f"Linked effective activity {aid!r} is {activity['status']}; excluded from received payments."})
            continue
        if activity['event_type'] != ann['income_type'] or aid not in rows:
            raise ValueError('Payment link must target the declared dividend/interest type; buy/reinvestment legs are excluded')
        row = rows[aid]
        if _scope_relation(activity, ann['scope']) is not True:
            raise ValueError('Payment link scope is incompatible or missing historical attribution')
        if row['currency'] != ann['money']['currency']:
            raise ValueError('Payment link currency differs from announced currency; no FX substitution')
        if ann['amount_basis'] == 'unknown' or row[ann['amount_basis']] is None:
            raise ValueError('Payment link amount basis is unknown or unavailable')
        if not _inside(row['date'], start, end):
            outside.add(ann_id)
            diagnostics.append({'id': ann_id, 'message': f"Linked effective payment {aid!r} dated {row['date']} is outside the selected period; excluded from selected received amount."})
            continue
        matched.setdefault(ann_id, []).append(row)
    return matched, outside


def _reconcile(announcement: dict[str, Any], payments: list[dict[str, Any]], outside: bool) -> dict[str, Any]:
    basis = announcement['amount_basis']
    subtotal = sum((Decimal(str(row[basis])) for row in payments), Decimal(0))
    expected = announcement['expected_amount']
    reason = None
    if announcement['status'] == 'cancelled':
        status, reason = 'cancelled', 'Latest announcement revision is cancelled; no entitlement calculated.'
    elif not payments:
        status = 'unlinked'
        reason = ('Reviewed payment exists outside the selected period; no received payment is counted in this window.'
                  if outside else 'No reviewed received-payment link in this period; payment coverage is unknown, not evidence of a late or missing payment.')
    elif expected is None:
        status, reason = 'unavailable', announcement['reason']
    else:
        difference = subtotal - Decimal(str(expected))
        status = 'matched' if difference == 0 else 'partial' if difference < 0 else 'overpaid'
        if outside:
            reason = 'Additional reviewed payments are outside the selected period; this comparison includes selected received payments only.'
    return {key: copy.deepcopy(announcement[key]) for key in
            ('scope', 'income_type', 'payment_date', 'currency', 'amount_basis', 'expected_amount')} | {
        'announcement_id': announcement['id'], 'received_amount': _json_number(subtotal) if payments else None,
        'known_received_subtotal': _json_number(subtotal),
        'activity_ids': sorted(row['activity_id'] for row in payments), 'status': status, 'reason': reason}


def _yield(row: dict[str, Any], received: dict[str, Any], effective: list[dict[str, Any]],
           start: str | None, end: str | None) -> dict[str, Any]:
    money, period, basis = row['money'], row['period'], row['amount_basis']
    result = {key: copy.deepcopy(row[key]) for key in ('id', 'scope', 'source', 'method', 'period', 'amount_basis')}
    result.update(currency=money['currency'] if money else None, cost_basis=money['amount'] if money else None,
                  received_amount=None, activity_ids=[], ratio=None, status='unavailable', reason=None)
    reason = None
    if money is None:
        reason = 'Declared cost basis is unavailable.'
    elif row['coverage'] != 'complete':
        reason = 'Income coverage for the declared scope, source and period is not complete.'
    elif basis == 'unknown':
        reason = 'Requested income amount basis is unknown.'
    elif not row.get('income_source_system'):
        reason = 'Income source system is unknown.'
    elif row['scope'].get('source_system', row['income_source_system']) != row['income_source_system']:
        reason = 'Declared scope source and income source system are incompatible.'
    elif (start and start > period['start']) or (end and end < period['end']):
        reason = 'Selected dates do not include the entire declared cost-basis period; no partial-period yield substituted.'
    candidates = []
    by_id = {a['id']: a for a in effective}
    if reason is None:
        for activity in effective:
            if activity['status'] != 'posted':
                continue
            affects_cost = (activity.get('event_type') in _COST_EVENTS
                            or 'cost_basis_adjustment' in activity or 'corporate_action' in activity)
            generic_income = activity.get('event_type') == 'income'
            if not (affects_cost or generic_income):
                continue
            day = _event_date(activity.get('effective_at'))
            relation = _scope_relation(activity, row['scope'])
            if _inside(day, period['start'], period['end']) and relation is not False:
                reason = ('Unclassified income prevents a complete received-income numerator.' if generic_income else
                          'Constant cost basis is unsupported because a cost-affecting activity occurs in the declared period.'
                          if relation else 'Cost-affecting activity has unknown historical scope; constant cost basis is unavailable.')
                break
    if reason is None:
        for event in received['events']:
            if not _inside(event['date'], period['start'], period['end']):
                continue
            activity = by_id[event['activity_id']]
            relation = _scope_relation(activity, row['scope'])
            if relation is False:
                continue
            if relation is None:
                reason = 'Received income has unknown historical scope attribution.'
                break
            if _activity_source(activity) != row['income_source_system']:
                reason = 'Received income source is unknown or incompatible with the declared income source.'
                break
            if event['currency'] != money['currency']:
                reason = 'Received income currency differs from declared cost currency; no FX substitution.'
                break
            if event[basis] is None:
                reason = 'Received income amount basis is unavailable.'
                break
            candidates.append(event)
    if reason:
        result['reason'] = reason
        return result
    total = sum((Decimal(str(event[basis])) for event in candidates), Decimal(0))
    result.update(received_amount=_json_number(total), activity_ids=sorted(event['activity_id'] for event in candidates),
                  ratio=_json_number(total / Decimal(str(money['amount']))), status='available')
    return result


def build_income_planning_report(
    portfolio: dict[str, Any], received_report: dict[str, Any], plan: dict[str, Any], *,
    start: str | None = None, end: str | None = None,
) -> dict[str, Any]:
    """Build announced, scenario, reconciliation, and declared-cost yield rows.

    Plans may be passed from local files or the portfolio extension by the
    caller. This function validates the standalone v1 plan, never modifies any
    input, resolves corrections before date filtering, and uses only canonical
    received events for financial comparisons. Dates are inclusive source-local
    calendar days. Ratios are never annualized. Invalid evidence raises ValueError;
    insufficient evidence yields null amounts/ratios with an explicit reason.
    """
    _validate_plan(plan)
    start, end = _bound(start, 'start'), _bound(end, 'end')
    if start and end and start > end:
        raise ValueError('start must be on or before end')
    received = _received(portfolio, received_report, start, end)
    announcements = _unique(plan.get('announcements', []), revisions=True)
    estimates = _unique(plan.get('estimates', []))
    costs = _unique(plan.get('cost_bases', []))
    diagnostics: list[dict[str, Any]] = []
    matched, outside = _links(portfolio, announcements, plan.get('payment_links', []), received, start, end, diagnostics)
    announced = []
    for row in announcements:
        if not _inside(row['payment_date'], start, end):
            continue
        amount, reason = None, None
        if row['status'] == 'cancelled':
            reason = 'Latest announcement revision is cancelled; no entitlement calculated.'
        elif row['amount_basis'] == 'unknown':
            reason = 'Announced income amount basis is unknown.'
        elif row['amount_kind'] == 'per_unit' and 'entitlement_quantity' not in row:
            reason = 'Per-unit announcement has no declared historical entitlement quantity; current holdings are not used.'
        else:
            amount = Decimal(str(row['money']['amount']))
            if row['amount_kind'] == 'per_unit':
                amount *= Decimal(str(row['entitlement_quantity']))
        row.update(currency=row['money']['currency'], expected_amount=_json_number(amount), reason=reason)
        announced.append(row)
    selected_estimates = []
    for row in estimates:
        if _inside(row['payment_date'], start, end):
            row.update(currency=row['money']['currency'], estimated_amount=row['money']['amount'])
            selected_estimates.append(row)
    effective = sorted(effective_activities(portfolio.get('activities', [])), key=lambda activity: activity['id'])
    return {'version': 1, 'start': start, 'end': end, 'announced': announced, 'estimates': selected_estimates,
            'reconciliation': [_reconcile(row, matched.get(row['id'], []), row['id'] in outside) for row in announced],
            'yield_on_cost': [_yield(row, received, effective, start, end) for row in costs],
            'diagnostics': diagnostics}
