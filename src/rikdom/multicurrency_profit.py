"""Reviewed v2 long-only FIFO, native cash conservation and dated FX attribution.

The single computation boundary owns the accounting convention: historical lot
costs and event cash are translated at their own dates, while valuation uses
bookend FX. Cash FX follows native balances and dated movements independently;
it is never inferred from the unexplained portfolio residual.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rfc3339_validator import validate_rfc3339
from decimal import Decimal

from .historical_fx import HistoricalFx
from .income import income_amount_basis
from .performance import PerformanceResult
from .profit_attribution import (
    _copy_evidence, _json, _keys, _number, _reviewed_history, _TOLERANCE,
)

ZERO = Decimal(0)
FX_COMPONENTS = (
    'realized_price_gain_base', 'realized_fx_gain_base',
    'opening_unrealized_price_gain_base', 'opening_unrealized_fx_gain_base',
    'closing_unrealized_price_gain_base', 'closing_unrealized_fx_gain_base',
    'unrealized_price_change_base', 'unrealized_fx_change_base',
    'cash_fx_gain_base', 'fx_conversion_result_base',
)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not validate_rfc3339(value):
        raise ValueError('Expected an RFC3339 timestamp with explicit timezone')
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def _known_by(value: object, cutoff: datetime) -> None:
    """Enforce retrieval knowledge across nested source and revision evidence."""
    if isinstance(value, dict):
        for field, child in value.items():
            if field in ('effective_at', 'retrieved_at', 'reviewed_at', 'ingested_at', 'created_at'):
                when = _timestamp(child)
                if field in ('retrieved_at', 'ingested_at', 'created_at') and when > cutoff:
                    raise ValueError('Source/revision provenance exceeds reviewed retrieval cutoff')
            _known_by(child, cutoff)
    elif isinstance(value, list):
        for child in value:
            _known_by(child, cutoff)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Explicit nonempty identity is required')
    return value


def _currency(value: object) -> str:
    code = _text(value)
    if len(code) != 3 or not code.isascii() or not code.isupper() or not code.isalpha():
        raise ValueError('Expected a three-letter uppercase currency')
    return code


def _position(row: dict) -> tuple[str, str, str]:
    return (_text(row.get('account_id')), _text(row.get('holding_id')), _currency(row.get('currency')))


def _cash(row: dict) -> tuple[str, str]:
    return (_text(row.get('account_id')), _currency(row.get('currency')))


def decompose_multicurrency(
    basis: dict, ledger: list[dict], performance: PerformanceResult, bridge: dict,
    raw_activities: list[dict], historical_fx: HistoricalFx | None,
) -> dict:
    """Return a fully reconciled v2 decomposition or reject incomplete evidence."""
    basis = _copy_evidence(basis)
    _keys(basis, {
        'contract_version', 'scope', 'base_currency', 'period_start', 'period_end',
        'method', 'price_adjustment', 'cost_convention', 'review', 'history',
        'inventory', 'opening_cash', 'closing_cash', 'opening_lots',
        'opening_positions', 'closing_positions',
    }, 'v2 profit basis')
    constants = {
        'contract_version': '2.0', 'scope': 'portfolio',
        'base_currency': performance.base_currency, 'method': 'fifo',
        'price_adjustment': 'unadjusted',
        'cost_convention': 'buy_costs_capitalized_sell_costs_deducted',
    }
    if any(basis[key] != value for key, value in constants.items()):
        raise ValueError('Unsupported v2 basis scope, currency, method or cost convention')
    base = _currency(performance.base_currency)
    start, end = _timestamp(performance.period_start), _timestamp(performance.period_end)
    if (_timestamp(basis['period_start']), _timestamp(basis['period_end'])) != (start, end):
        raise ValueError('Basis period must equal performance bookends')
    review = _keys(basis['review'], {'status', 'source', 'reviewed_at', 'retrieved_before'}, 'review')
    _text(review['source'])
    reviewed, cutoff = _timestamp(review['reviewed_at']), _timestamp(review['retrieved_before'])
    if review['status'] != 'reviewed' or not end <= cutoff <= reviewed:
        raise ValueError('Explicit reviewed evidence and retrieval cutoff must cover period')
    history = _keys(basis['history'], {'status', 'from', 'through', 'missing_periods'}, 'history')
    if (history['status'] != 'complete' or history['missing_periods'] != []
            or (_timestamp(history['from']), _timestamp(history['through'])) != (start, end)):
        raise ValueError('Explicit complete history must cover exactly the period')
    history_evidence = _reviewed_history(raw_activities, start, end, cutoff)
    _known_by(history_evidence['activities'], cutoff)
    if historical_fx is not None and historical_fx.base_currency != base:
        raise ValueError('Historical FX reporting currency differs from basis')
    fx_evidence = []

    def rate(code: str, when: datetime, purpose: str, identity: str) -> Decimal:
        _currency(code)
        if historical_fx is None:
            if code != base:
                raise ValueError(f'Missing dated historical FX for {code} at {when.isoformat()}')
            evidence = {'identity': True, 'rate': 1, 'as_of': when.isoformat(),
                        'currency_pair': {'base': base, 'quote': base}}
            value = Decimal(1)
        else:
            lookup = historical_fx.resolve(code, when)
            if lookup.rate is None:
                raise ValueError(f'Historical FX unavailable for {code}: {lookup.reason}')
            evidence = _copy_evidence(lookup.evidence)
            value = _number(lookup.rate)
            if value <= 0:
                raise ValueError('Historical FX must be positive')
            _known_by(evidence, cutoff)
        fx_evidence.append({'purpose': purpose, 'identity': identity, 'evidence': evidence})
        return value

    inventory = _keys(basis['inventory'], {'status', 'account_ids', 'positions', 'cash'}, 'inventory')
    if inventory['status'] != 'complete':
        raise ValueError('Complete portfolio account, position and cash inventory required')
    for name in ('account_ids', 'positions', 'cash'):
        if not isinstance(inventory[name], list):
            raise ValueError('Inventory identities must be arrays')
    accounts = {_text(item) for item in inventory['account_ids']}
    if len(accounts) != len(inventory['account_ids']):
        raise ValueError('Duplicate account inventory')
    identities = set()
    cash_ids = set()
    for row in inventory['positions']:
        _keys(row, {'account_id', 'holding_id', 'currency'}, 'position inventory')
        key = _position(row)
        if key in identities or key[0] not in accounts:
            raise ValueError('Duplicate or unknown inventory position')
        identities.add(key)
    if len({key[:2] for key in identities}) != len(identities):
        raise ValueError('A holding/account identity must have one native currency')
    for row in inventory['cash']:
        _keys(row, {'account_id', 'currency'}, 'cash inventory')
        key = _cash(row)
        if key in cash_ids or key[0] not in accounts:
            raise ValueError('Duplicate or unknown inventory cash')
        cash_ids.add(key)
    positions = []
    balances = []
    bookend_rates = []
    for prefix, when, expected in [('opening', start, bridge['opening_value_base']),
                                   ('closing', end, bridge['closing_value_base'])]:
        parsed = {}
        cash = {}
        for name in (prefix + '_positions', prefix + '_cash'):
            if not isinstance(basis[name], list):
                raise ValueError(f'{name} must be an array')
        total = ZERO
        rates = {}
        for row in basis[prefix + '_positions']:
            _keys(row, {'account_id', 'holding_id', 'currency', 'quantity', 'market_value_native'}, 'position')
            key = _position(row)
            if key not in identities or key in parsed:
                raise ValueError('Position differs from complete inventory')
            qty, nav = _number(row['quantity']), _number(row['market_value_native'])
            if qty == 0 and nav != 0:
                raise ValueError('Zero quantity cannot carry market value')
            r = rate(key[2], when, prefix + '_position', '/'.join(key))
            parsed[key] = (qty, nav)
            rates[key] = r
            total += nav * r
        for row in basis[prefix + '_cash']:
            _keys(row, {'account_id', 'currency', 'amount'}, 'cash')
            key = _cash(row)
            if key not in cash_ids or key in cash:
                raise ValueError('Cash differs from complete inventory')
            cash[key] = _number(row['amount'])
            r = rate(key[1], when, prefix + '_cash', '/'.join(key))
            rates[key] = r
            total += cash[key] * r
        if set(parsed) != identities or set(cash) != cash_ids:
            raise ValueError('Every inventory identity needs explicit opening and closing evidence, including zero')
        if abs(total - Decimal(str(expected))) > _TOLERANCE:
            raise ValueError('Reviewed native cash and positions do not reconcile with performance bookend')
        positions.append(parsed)
        balances.append(cash)
        bookend_rates.append(rates)
    opening, closing = positions
    opening_cash, closing_cash = balances
    current_cash = dict(opening_cash)
    translated_deltas = {key: ZERO for key in cash_ids}
    lots = {key: [] for key in identities}
    if not isinstance(basis['opening_lots'], list):
        raise ValueError('opening_lots must be an array')
    lot_ids = set()
    acquisition_times = set()
    for row in basis['opening_lots']:
        _keys(row, {'id', 'account_id', 'holding_id', 'currency', 'acquired_at', 'quantity', 'total_cost_native'}, 'opening lot')
        key = _position(row)
        aid, acquired = _text(row['id']), _timestamp(row['acquired_at'])
        qty, cost = _number(row['quantity']), _number(row['total_cost_native'])
        if key not in identities or aid in lot_ids or acquired > start or qty <= 0 or (key, acquired) in acquisition_times:
            raise ValueError('Opening lots require unique IDs, inventory and unambiguous historical acquisition dates')
        r = rate(key[2], acquired, 'opening_lot', aid)
        lots[key].append({'id': aid, 'when': acquired, 'quantity': qty, 'native_cost': cost, 'base_cost': cost * r})
        lot_ids.add(aid)
        acquisition_times.add((key, acquired))
    for key, rows in lots.items():
        rows.sort(key=lambda lot: lot['when'])
        if sum((row['quantity'] for row in rows), ZERO) != opening[key][0]:
            raise ValueError('Opening lots do not reconcile with opening position quantity')
    opening_costs = {key: (sum((r['native_cost'] for r in rows), ZERO),
                           sum((r['base_cost'] for r in rows), ZERO)) for key, rows in lots.items()}
    realized_price = {key: ZERO for key in identities}
    realized_fx = dict(realized_price)
    net_income = fees_total = taxes_total = conversion_result = ZERO
    activity_evidence = []
    chronological = []
    inventory_times = set()
    for activity in ledger:
        when = _timestamp(activity.get('effective_at'))
        if start <= when <= end:
            if when == start:
                raise ValueError('Events at opening bookend have ambiguous inclusion')
            chronological.append((when, activity))
    for when, activity in sorted(chronological, key=lambda item: (item[0], item[1]['id'])):
        event = str(activity.get('event_type', '')).strip().lower()
        aid, account = activity['id'], _text(activity.get('account_id'))
        if account not in accounts:
            raise ValueError('Activity account is absent from complete inventory')
        if 'cost_basis_adjustment' in activity:
            raise ValueError('Unsupported cost_basis_adjustment')
        cash_movements = []

        def movement(code: str, amount: Decimal, purpose: str) -> Decimal:
            key = (account, code)
            if key not in cash_ids:
                raise ValueError('Activity cash currency/account absent from inventory')
            r = rate(code, when, purpose, aid)
            current_cash[key] += amount
            translated_deltas[key] += amount * r
            cash_movements.append({'currency': code, 'amount_native': _json(amount), 'amount_base': _json(amount * r)})
            return amount * r

        row = {'activity_id': aid, 'event_type': event, 'effective_at': activity['effective_at'],
               'cash_movements': cash_movements, 'provenance': 'computed_from_reported_ledger'}
        if event == 'split':
            action = activity.get('corporate_action')
            if not isinstance(action, dict) or action.get('kind') not in ('split', 'reverse_split'):
                raise ValueError('Split requires explicit supported corporate_action')
            ratio = _number(action.get('exchange_ratio'))
            _keys(action, {'kind', 'exchange_ratio', 'legs'}, 'split corporate_action')
            if ratio <= 0 or (action['kind'] == 'reverse_split' and ratio >= 1) or (action['kind'] == 'split' and ratio < 1):
                raise ValueError('Split exchange ratio must be positive and agree with action kind')
            matching = [key for key in identities if key[:2] == (account, activity.get('holding_id'))]
            if len(matching) != 1:
                raise ValueError('Split holding/account absent from inventory')
            key = matching[0]
            if (key, when) in inventory_times:
                raise ValueError('Same-instant inventory movements are ambiguous')
            inventory_times.add((key, when))
            quantity = sum((lot['quantity'] for lot in lots[key]), ZERO)
            delta = quantity * (ratio - 1)
            if quantity <= 0 or action.get('legs') is None:
                raise ValueError('Split requires positive inventory and explicit quantity delta')
            legs = action['legs']
            if (not isinstance(legs, list) or len(legs) != 1 or not isinstance(legs[0], dict)
                    or legs[0].get('holding_id') != key[1]
                    or _number(legs[0].get('quantity_delta'), signed=True) != delta):
                raise ValueError('Split quantity delta disagrees with ratio and reviewed inventory')
            _keys(legs[0], {'holding_id', 'quantity_delta'}, 'split leg without basis adjustments')
            if 'quantity' in activity and _number(activity['quantity'], signed=True) != delta:
                raise ValueError('Split activity quantity disagrees with reviewed delta')
            for field in ('money', 'fees', 'withholding_tax'):
                if field in activity and _number(activity[field].get('amount')) != 0:
                    raise ValueError('Split cash/basis adjustments are unsupported')
            for lot in lots[key]:
                lot['quantity'] *= ratio
            row.update(quantity_before=_json(quantity), quantity_after=_json(quantity * ratio), exchange_ratio=_json(ratio))
            activity_evidence.append(row)
            continue
        if 'corporate_action' in activity:
            raise ValueError('Unsupported corporate action')
        if activity.get('holding_id') and not any(
            key[:2] == (account, activity['holding_id']) for key in identities
        ):
            raise ValueError('Activity holding/account absent from complete inventory')
        if event not in {'buy', 'sell', 'dividend', 'interest', 'income', 'fee', 'tax_withheld',
                         'contribution', 'withdrawal', 'transfer_in', 'transfer_out', 'fx_conversion'}:
            raise ValueError(f'Unsupported movement {event!r}')
        if event not in ('buy', 'sell') and 'quantity' in activity and _number(activity['quantity'], signed=True) != 0:
            raise ValueError('Unsupported non-trade quantity movement')
        money = _keys(activity.get('money'), {'amount', 'currency'}, 'activity money')
        code = _currency(money['currency'])
        amount = _number(money['amount'], signed=event in ('contribution', 'withdrawal', 'transfer_in', 'transfer_out'))
        r = rate(code, when, 'activity_money', aid)
        charges = []
        for field in ('fees', 'withholding_tax'):
            charge = activity.get(field, {'amount': 0, 'currency': code})
            _keys(charge, {'amount', 'currency'}, field)
            ccode, charge_amount = _currency(charge['currency']), _number(charge['amount'])
            converted = charge_amount * rate(ccode, when, field, aid)
            charges.append((ccode, charge_amount, converted))
        fees, taxes = charges
        charge_base = fees[2] + taxes[2]
        row.update(reported_amount_native=_json(amount), native_currency=code,
                   reported_fees=activity.get('fees'), reported_taxes=activity.get('withholding_tax'),
                   applied_charges_base=_json(charge_base))
        apply_charges = True
        if event in ('buy', 'sell'):
            key = (account, _text(activity.get('holding_id')), code)
            if key not in identities:
                raise ValueError('Trade holding/account/currency absent from inventory')
            qty = _number(activity.get('quantity'))
            if qty <= 0 or (key, when) in inventory_times:
                raise ValueError('Trades require positive quantity and unambiguous inventory timestamps')
            inventory_times.add((key, when))
            rows = lots[key]
            if event == 'buy':
                if aid in lot_ids:
                    raise ValueError('Trade ID collides with opening lot')
                lot_ids.add(aid)
                cost = amount + charge_base / r
                rows.append({'id': aid, 'when': when, 'quantity': qty,
                             'native_cost': cost, 'base_cost': amount * r + charge_base})
                movement(code, -amount, 'trade_cash')
                row.update(capitalized_cost_native=_json(cost), capitalized_cost_base=_json(amount * r + charge_base))
            else:
                remainder, cost, historical_cost = qty, ZERO, ZERO
                consumed = []
                for lot in rows:
                    take = min(remainder, lot['quantity'])
                    if not take:
                        continue
                    native = lot['native_cost'] * take / lot['quantity']
                    base_cost = lot['base_cost'] * take / lot['quantity']
                    lot['quantity'] -= take
                    lot['native_cost'] -= native
                    lot['base_cost'] -= base_cost
                    remainder -= take
                    cost += native
                    historical_cost += base_cost
                    consumed.append({'lot_id': lot['id'], 'quantity': _json(take),
                                     'cost_native': _json(native), 'historical_cost_base': _json(base_cost)})
                    if not remainder:
                        break
                if remainder:
                    raise ValueError('Sale exceeds reviewed FIFO inventory')
                price_gain = (amount - cost) * r - charge_base
                fx_gain = cost * r - historical_cost
                realized_price[key] += price_gain
                realized_fx[key] += fx_gain
                movement(code, amount, 'trade_cash')
                row.update(consumed_lots=consumed, realized_price_gain_base=_json(price_gain), realized_fx_gain_base=_json(fx_gain))
        elif event in ('dividend', 'interest', 'income'):
            income_basis = income_amount_basis(activity)
            if income_basis == 'unknown':
                raise ValueError('Income receipt amount basis is unknown')
            if income_basis == 'net':
                if any(c[1] and c[0] != code for c in charges):
                    raise ValueError('Net income with cross-currency charges is ambiguous; gross evidence required')
                apply_charges = False
                net_income += amount * r
            else:
                net_income += amount * r - charge_base
            movement(code, amount, 'income_cash')
            row['income_amount_basis'] = income_basis
        elif event in ('fee', 'tax_withheld'):
            movement(code, -amount, 'standalone_charge_cash')
            fees_total += fees[2] + (amount * r if event == 'fee' else ZERO)
            taxes_total += taxes[2] + (amount * r if event == 'tax_withheld' else ZERO)
        elif event == 'fx_conversion':
            if activity.get('holding_id'):
                raise ValueError('FX conversion must be cash-only')
            counter = _keys(activity.get('counter_money'), {'amount', 'currency'}, 'counter_money')
            other, bought = _currency(counter['currency']), _number(counter['amount'])
            if other == code or amount <= 0 or bought <= 0:
                raise ValueError('FX conversion needs distinct currencies and positive explicit legs')
            if 'fx_rate' in activity:
                quoted = _number(activity['fx_rate'])
                if quoted <= 0 or abs(amount * quoted - bought) > _TOLERANCE:
                    raise ValueError('FX conversion quote disagrees with explicit legs')
            sold_base = movement(code, -amount, 'fx_sold_cash')
            bought_base = movement(other, bought, 'fx_bought_cash')
            conversion_result += sold_base + bought_base
            fees_total += fees[2]
            taxes_total += taxes[2]
            row['fx_conversion_result_base'] = _json(sold_base + bought_base)
        else:
            if charge_base or activity.get('holding_id') or activity.get('quantity'):
                raise ValueError('External/internal flows require cash-only evidence without charges')
            direction = -1 if event in ('withdrawal', 'transfer_out') else 1
            movement(code, abs(amount) * direction, 'external_or_internal_cash')
        if apply_charges:
            for ccode, charge_amount, _ in charges:
                if charge_amount:
                    movement(ccode, -charge_amount, 'embedded_charge_cash')
        if any(value < 0 for value in current_cash.values()):
            raise ValueError('Negative cash requires unsupported debt/margin accounting')
        activity_evidence.append(_copy_evidence(row))
    cash_evidence = []
    cash_fx = ZERO
    for key in sorted(cash_ids):
        if abs(current_cash[key] - closing_cash[key]) > _TOLERANCE:
            raise ValueError('Native cash movements do not reconcile with reviewed closing cash')
        gain = (closing_cash[key] * bookend_rates[1][key]
                - opening_cash[key] * bookend_rates[0][key] - translated_deltas[key])
        cash_fx += gain
        cash_evidence.append({'account_id': key[0], 'currency': key[1],
                              'opening_native': _json(opening_cash[key]), 'closing_native': _json(closing_cash[key]),
                              'event_cash_delta_base': _json(translated_deltas[key]), 'cash_fx_gain_base': _json(gain)})
    holding_evidence = []
    op = of = cp = cf = ZERO
    for key in sorted(identities):
        quantity = sum((lot['quantity'] for lot in lots[key]), ZERO)
        if quantity != closing[key][0]:
            raise ValueError('Closing quantity differs from reconstructed FIFO inventory')
        native_cost = sum((lot['native_cost'] for lot in lots[key]), ZERO)
        base_cost = sum((lot['base_cost'] for lot in lots[key]), ZERO)
        oc, ob = opening_costs[key]
        opening_price = (opening[key][1] - oc) * bookend_rates[0][key]
        opening_fx = oc * bookend_rates[0][key] - ob
        closing_price = (closing[key][1] - native_cost) * bookend_rates[1][key]
        closing_fx = native_cost * bookend_rates[1][key] - base_cost
        op += opening_price
        of += opening_fx
        cp += closing_price
        cf += closing_fx
        holding_evidence.append({'account_id': key[0], 'holding_id': key[1], 'native_currency': key[2],
                                 'closing_quantity': _json(quantity), 'remaining_cost_native': _json(native_cost),
                                 'remaining_historical_cost_base': _json(base_cost),
                                 'realized_price_gain_base': _json(realized_price[key]),
                                 'realized_fx_gain_base': _json(realized_fx[key]),
                                 'opening_unrealized_price_gain_base': _json(opening_price),
                                 'opening_unrealized_fx_gain_base': _json(opening_fx),
                                 'closing_unrealized_price_gain_base': _json(closing_price),
                                 'closing_unrealized_fx_gain_base': _json(closing_fx)})
    rp, rf = sum(realized_price.values(), ZERO), sum(realized_fx.values(), ZERO)
    explained = rp + rf + cp + cf - op - of + net_income - fees_total - taxes_total + cash_fx + conversion_result
    difference = Decimal(str(bridge['investment_result_base'])) - explained
    if abs(difference) > _TOLERANCE:
        raise ValueError('Price, FX, income and charge components do not reconcile with period result')
    components = {
        'realized_gain_base': rp + rf, 'realized_price_gain_base': rp, 'realized_fx_gain_base': rf,
        'opening_unrealized_gain_base': op + of, 'closing_unrealized_gain_base': cp + cf,
        'unrealized_change_base': cp + cf - op - of,
        'opening_unrealized_price_gain_base': op, 'opening_unrealized_fx_gain_base': of,
        'closing_unrealized_price_gain_base': cp, 'closing_unrealized_fx_gain_base': cf,
        'unrealized_price_change_base': cp - op, 'unrealized_fx_change_base': cf - of,
        'cash_fx_gain_base': cash_fx, 'fx_conversion_result_base': conversion_result,
        'net_income_base': net_income, 'standalone_fees_base': fees_total,
        'standalone_taxes_base': taxes_total, 'explained_result_base': explained,
        'reconciliation_difference_base': difference,
    }
    return {'status': 'complete', 'contract_version': '2.0', 'method': 'fifo',
            **{key: _json(value) for key, value in components.items()},
            'holdings': holding_evidence, 'cash_evidence': cash_evidence,
            'activity_evidence': activity_evidence, 'fx_evidence': fx_evidence,
            'basis_evidence': basis, 'history_evidence': history_evidence}
