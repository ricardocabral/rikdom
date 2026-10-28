"""Financial behavior of evidence-backed planning, separate from received income."""
import copy
import json
from pathlib import Path
import unittest

from rikdom.income import build_income_report
from rikdom.income_planning import build_income_planning_report


def source(reference='reviewed local statement'):
    return {'kind': 'manual', 'reference': reference, 'as_of': '2026-01-31'}


def payment(aid='pay', amount=10, **fields):
    return {'id': aid, 'status': 'posted', 'event_type': 'dividend',
            'effective_at': '2026-01-15T12:00:00-03:00',
            'money': {'amount': amount, 'currency': 'USD'}, 'holding_id': 'h',
            'account_id': 'a', 'provenance': {'source_system': 'broker'}, **fields}


def announcement(aid='ann', **fields):
    return {'id': aid, 'revision': 1, 'status': 'announced', 'source': source(),
            'scope': {'holding_id': 'h', 'account_id': 'a'}, 'income_type': 'dividend',
            'payment_date': '2026-01-15', 'money': {'amount': 10, 'currency': 'USD'},
            'amount_basis': 'gross', 'amount_kind': 'total', **fields}


def cost(**fields):
    return {'id': 'cost', 'scope': {'holding_id': 'h', 'account_id': 'a'}, 'source': source(),
            'method': 'declared_constant_cost', 'period': {'start': '2026-01-01', 'end': '2026-01-31'},
            'money': {'amount': 100, 'currency': 'USD'}, 'amount_basis': 'gross',
            'coverage': 'complete', 'income_source_system': 'broker', **fields}


def plan(**fields):
    return {'version': 1, 'announcements': [], 'estimates': [], 'payment_links': [],
            'cost_bases': [], **fields}


def portfolio(*events):
    return {'schema_version': '2.0.0', 'activities': list(events)}


def build(p=None, config=None, **bounds):
    p = p if p is not None else portfolio()
    return build_income_planning_report(p, build_income_report(p, **bounds), config or plan(), **bounds)


class IncomePlanningTests(unittest.TestCase):
    def test_revisions_deduplicate_latest_wins_and_cancellation_has_no_entitlement(self):
        old = announcement()
        latest = announcement(revision=2, money={'amount': 12, 'currency': 'USD'})
        cancelled = announcement('cancelled', revision=3, status='cancelled')
        config = plan(announcements=[latest, old, latest, cancelled])
        result = build(config=config)
        self.assertEqual([(a['id'], a['expected_amount']) for a in result['announced']],
                         [('ann', 12), ('cancelled', None)])
        self.assertEqual(result, build(config=plan(announcements=list(reversed(config['announcements'])))))
        self.assertEqual(result['reconciliation'][1]['status'], 'cancelled')
        with self.assertRaisesRegex(ValueError, 'revision'):
            build(config=plan(announcements=[old, announcement(money={'amount': 11, 'currency': 'USD'})]))

    def test_entitlement_is_declared_and_scenarios_never_enter_actual_income(self):
        config = plan(announcements=[announcement(amount_kind='per_unit')], estimates=[{
            'id': 'scenario', 'scenario': 'optimistic', 'source': source(),
            'scope': {'holding_id': 'h'}, 'income_type': 'dividend', 'payment_date': '2026-02-15',
            'money': {'amount': 999, 'currency': 'USD'}, 'amount_basis': 'gross',
            'assumptions': 'Illustrative only'}], cost_bases=[cost()])
        p = portfolio(payment())
        p['holdings'] = [{'id': 'h', 'quantity': 100000}]
        result = build(p, config)
        self.assertIsNone(result['announced'][0]['expected_amount'])
        self.assertIn('entitlement', result['announced'][0]['reason'].lower())
        self.assertEqual(result['estimates'][0]['estimated_amount'], 999)
        self.assertEqual(result['yield_on_cost'][0]['ratio'], .1)
        config['announcements'][0].update(entitlement_quantity=3, entitlement_source=source('record-date statement'))
        self.assertEqual(build(p, config)['announced'][0]['expected_amount'], 30)

    def test_only_explicit_links_match_and_effective_payment_is_counted_once(self):
        first = payment()
        replacement = payment('corrected', amount=12, extensions={'rikdom_correction': {
            'version': 1, 'supersedes_activity_id': 'pay', 'reason': 'corrected source'}})
        p = portfolio(first, replacement, payment('same-amount', amount=10))
        config = plan(announcements=[announcement(money={'amount': 12, 'currency': 'USD'})],
                      cost_bases=[cost()])
        self.assertEqual(build(p, config)['reconciliation'][0]['status'], 'unlinked')
        config['payment_links'] = [{'announcement_id': 'ann', 'activity_id': aid, 'source': source()}
                                   for aid in ('pay', 'pay', 'corrected')]
        row = build(p, config)['reconciliation'][0]
        self.assertEqual((row['status'], row['received_amount'], row['activity_ids']),
                         ('matched', 12, ['corrected']))
        self.assertEqual(build(p, config)['yield_on_cost'][0]['received_amount'], 22)
        config['announcements'].append(announcement('other'))
        config['payment_links'].append({'announcement_id': 'other', 'activity_id': 'corrected', 'source': source()})
        with self.assertRaisesRegex(ValueError, 'assigned'):
            build(p, config)

    def test_links_reject_wrong_scope_currency_type_basis_and_unknown_identity(self):
        config = plan(announcements=[announcement()], payment_links=[{
            'announcement_id': 'ann', 'activity_id': 'pay', 'source': source()}])
        for fields in ({'holding_id': 'other'}, {'holding_id': None},
                       {'money': {'amount': 10, 'currency': 'EUR'}},
                       {'event_type': 'interest'}, {'event_type': 'buy'},
                       {'metadata': {'rikdom_income': {'version': 1, 'amount_basis': 'unknown'}}}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                build(portfolio(payment(**fields)), config)
        for key, value in [('activity_id', 'missing'), ('announcement_id', 'missing')]:
            invalid = copy.deepcopy(config)
            invalid['payment_links'][0][key] = value
            with self.assertRaises(ValueError):
                build(portfolio(payment()), invalid)
        scoped = copy.deepcopy(config)
        scoped['announcements'][0]['scope']['source_system'] = 'other'
        with self.assertRaises(ValueError):
            build(portfolio(payment()), scoped)

    def test_source_identity_uses_asserted_top_level_or_provenance_and_rejects_conflicts(self):
        p = portfolio(payment(provenance={}, source_system='broker'))
        self.assertEqual(build(p, plan(cost_bases=[cost()]))['yield_on_cost'][0]['ratio'], .1)
        p = portfolio(payment(source_system='different'))
        row = build(p, plan(cost_bases=[cost()]))['yield_on_cost'][0]
        self.assertEqual(row['status'], 'unavailable')
        self.assertIn('source', row['reason'].lower())
        c = cost(scope={'holding_id': 'h', 'source_system': 'other'})
        row = build(portfolio(), plan(cost_bases=[c]))['yield_on_cost'][0]
        self.assertEqual(row['status'], 'unavailable')

    def test_cancelled_announcement_excludes_historical_link_but_preserves_received_income(self):
        config = plan(announcements=[announcement(), announcement(revision=2, status='cancelled')],
                      payment_links=[{'announcement_id': 'ann', 'activity_id': 'pay', 'source': source()}],
                      cost_bases=[cost()])
        result = build(portfolio(payment()), config)
        row = result['reconciliation'][0]
        self.assertEqual((row['status'], row['expected_amount'], row['activity_ids']), ('cancelled', None, []))
        self.assertEqual(result['yield_on_cost'][0]['ratio'], .1)
        self.assertTrue(result['diagnostics'])

    def test_pending_cancelled_and_corrected_cancelled_links_do_not_count(self):
        config = plan(announcements=[announcement()], payment_links=[{
            'announcement_id': 'ann', 'activity_id': 'pay', 'source': source()}])
        for p in (portfolio(payment(status='pending')), portfolio(payment(status='cancelled')),
                  portfolio(payment(), payment('cancel', status='cancelled', extensions={
                      'rikdom_correction': {'version': 1, 'supersedes_activity_id': 'pay', 'reason': 'void'}}))):
            with self.subTest(p=p):
                row = build(p, config)['reconciliation'][0]
                self.assertEqual((row['status'], row['activity_ids']), ('unlinked', []))
                self.assertTrue(build(p, config)['diagnostics'])

    def test_partial_and_overpayment_are_explicit_comparisons_not_coverage_claims(self):
        config = plan(announcements=[announcement()], payment_links=[{
            'announcement_id': 'ann', 'activity_id': 'pay', 'source': source()}])
        for amount, status in [(4, 'partial'), (10, 'matched'), (12, 'overpaid')]:
            with self.subTest(amount=amount):
                row = build(portfolio(payment(amount=amount)), config)['reconciliation'][0]
                self.assertEqual((row['status'], row['received_amount']), (status, amount))
        row = build(config=plan(announcements=[announcement(payment_date='2000-01-01')]))['reconciliation'][0]
        self.assertEqual(row['status'], 'unlinked')
        self.assertIn('coverage', row['reason'].lower())

    def test_yield_is_native_received_only_declared_period_and_never_annualized(self):
        p = portfolio(payment(amount=10), payment('reinvest', amount=500, event_type='buy', effective_at='2025-01-01T00:00:00Z'),
                      payment('pending', amount=100, status='pending'),
                      payment('old', amount=200, effective_at='2025-12-31T23:30:00-03:00'),
                      payment('other', amount=300, holding_id='other'), payment('adjustment', amount=-2))
        config = plan(cost_bases=[cost()])
        row = build(p, config)['yield_on_cost'][0]
        self.assertEqual((row['status'], row['cost_basis'], row['received_amount'], row['ratio']),
                         ('available', 100, 8, .08))
        self.assertEqual(row['activity_ids'], ['adjustment', 'pay'])
        self.assertEqual(row['period'], {'start': '2026-01-01', 'end': '2026-01-31'})
        row = build(p, config, start='2026-01-15', end='2026-01-15')['yield_on_cost'][0]
        self.assertEqual(row['status'], 'unavailable')
        self.assertIn('period', row['reason'].lower())

    def test_constant_cost_rejects_cost_changes_instead_of_using_a_stale_denominator(self):
        for event_type in ('buy', 'sell', 'transfer_in', 'transfer_out', 'split', 'amortization'):
            with self.subTest(event_type=event_type):
                row = build(portfolio(payment(), payment('change', event_type=event_type)),
                            plan(cost_bases=[cost()]))['yield_on_cost'][0]
                self.assertEqual(row['status'], 'unavailable')
                self.assertIn('cost', row['reason'].lower())
                self.assertIsNone(row['ratio'])

    def test_account_constant_cost_rejects_capital_changes_and_ambiguous_attribution(self):
        for event_type in ('contribution', 'withdrawal', 'deposit'):
            for change_account in ('a', None):
                with self.subTest(event_type=event_type, change_account=change_account):
                    declaration = cost(scope={'account_id': 'a'}, money={'amount': 1000, 'currency': 'USD'})
                    config = plan(cost_bases=[declaration])
                    p = portfolio(payment(amount=50), payment('capital-change', amount=30,
                                  event_type=event_type, account_id=change_account))
                    before = copy.deepcopy((p, config))
                    row = build(p, config)['yield_on_cost'][0]
                    self.assertEqual(row['status'], 'unavailable')
                    self.assertIsNone(row['ratio'])
                    self.assertIsNone(row['received_amount'])
                    self.assertEqual(row['coverage'], 'complete')
                    self.assertEqual(row['income_source_system'], 'broker')
                    self.assertIn('cost', row['reason'].lower())
                    self.assertEqual((p, config), before)

    def test_constant_cost_ignores_known_unrelated_account_or_source_capital_changes(self):
        for event_type in ('contribution', 'withdrawal', 'deposit'):
            for scope, change in [
                ({'account_id': 'a'}, {'account_id': 'other'}),
                ({'account_id': 'a', 'source_system': 'broker'},
                 {'provenance': {'source_system': 'other-source'}}),
            ]:
                with self.subTest(event_type=event_type, scope=scope, change=change):
                    config = plan(cost_bases=[cost(scope=scope, money={'amount': 1000, 'currency': 'USD'})])
                    p = portfolio(payment(amount=50), payment('capital-change', amount=30,
                                  event_type=event_type, **change))
                    before = copy.deepcopy((p, config))
                    row = build(p, config)['yield_on_cost'][0]
                    self.assertEqual((row['status'], row['received_amount'], row['ratio']), ('available', 50, .05))
                    self.assertEqual(row['activity_ids'], ['pay'])
                    self.assertEqual((p, config), before)

    def test_declared_cost_cannot_hide_explicit_delta_or_unclassified_income(self):
        for activity in (payment('change', event_type='other',
                                cost_basis_adjustment={'amount': -5, 'currency': 'USD'}),
                         payment('generic', event_type='income')):
            with self.subTest(activity=activity):
                row = build(portfolio(payment(), activity), plan(cost_bases=[cost()]))['yield_on_cost'][0]
                self.assertEqual(row['status'], 'unavailable')
                self.assertIsNone(row['ratio'])

    def test_links_outside_selected_dates_remain_explicitly_explained(self):
        config = plan(announcements=[announcement()], payment_links=[{
            'announcement_id': 'ann', 'activity_id': 'pay', 'source': source()}])
        p = portfolio(payment(), payment('later', effective_at='2026-02-01T00:00:00Z',
                       extensions={'rikdom_correction': {'version': 1,
                       'supersedes_activity_id': 'pay', 'reason': 'date corrected'}}))
        result = build(p, config, start='2026-01-01', end='2026-01-31')
        self.assertEqual(result['reconciliation'][0]['received_amount'], None)
        self.assertIn('outside', result['reconciliation'][0]['reason'].lower())
        self.assertEqual(len(result['diagnostics']), 1)

    def test_filtered_partial_comparison_explains_additional_outside_window_receipts(self):
        config = plan(announcements=[announcement()], payment_links=[{
            'announcement_id': 'ann', 'activity_id': aid, 'source': source()} for aid in ('pay', 'later')])
        p = portfolio(payment(amount=4), payment('later', amount=6, effective_at='2026-02-01T00:00:00Z'))
        row = build(p, config, start='2026-01-01', end='2026-01-31')['reconciliation'][0]
        self.assertEqual((row['status'], row['received_amount']), ('partial', 4))
        self.assertIn('outside', row['reason'].lower())

    def test_shipped_synthetic_plan_calculates_fifty_received_over_one_thousand_cost(self):
        config = json.loads((Path(__file__).parent / 'fixtures' / 'income_plan.json').read_text())
        p = portfolio(payment('payment-1', amount=50, holding_id='holding-1',
                              provenance={'source_system': 'sample-broker'},
                              effective_at='2026-02-01T00:00:00Z'))
        result = build(p, config)
        self.assertEqual(result['reconciliation'][0]['status'], 'matched')
        self.assertEqual(result['yield_on_cost'][0]['ratio'], .05)
        self.assertEqual(result['estimates'][0]['estimated_amount'], 999)

    def test_unavailable_reason_is_independent_of_ledger_order(self):
        changes = [payment('z-buy', event_type='buy'), payment('a-generic', event_type='income')]
        config = plan(cost_bases=[cost()])
        self.assertEqual(build(portfolio(*changes), config), build(portfolio(*reversed(changes)), config))

    def test_yield_unknown_cost_coverage_basis_source_and_currency_are_unavailable(self):
        cases = [({'money': None}, payment(), 'cost'), ({'coverage': 'unknown'}, payment(), 'coverage'),
                 ({'coverage': 'partial'}, payment(), 'coverage'),
                 ({'amount_basis': 'unknown'}, payment(), 'basis'),
                 ({'income_source_system': None}, payment(), 'source'),
                 ({}, payment(provenance={}), 'source'),
                 ({}, payment(provenance={'source_system': 'other'}), 'source'),
                 ({}, payment(metadata={'rikdom_income': {'version': 1, 'amount_basis': 'unknown'}}), 'basis'),
                 ({'amount_basis': 'net'}, payment(), 'basis'),
                 ({}, payment(money={'amount': 10, 'currency': 'EUR'}), 'currency')]
        for fields, activity, reason in cases:
            with self.subTest(fields=fields, activity=activity):
                c = cost(**fields)
                if c.get('income_source_system') is None:
                    c.pop('income_source_system', None)
                row = build(portfolio(activity), plan(cost_bases=[c]))['yield_on_cost'][0]
                self.assertEqual(row['status'], 'unavailable')
                self.assertIsNone(row['ratio'])
                self.assertIsNone(row['received_amount'])
                self.assertIn(reason, row['reason'].lower())

    def test_yield_retains_declared_coverage_and_income_source_for_audit_without_mutation(self):
        for coverage, declared_source, status in [('complete', 'broker', 'available'),
                                                   ('partial', 'broker', 'unavailable'),
                                                   ('unknown', None, 'unavailable')]:
            with self.subTest(coverage=coverage, declared_source=declared_source):
                declaration = cost(coverage=coverage)
                if declared_source is None:
                    declaration.pop('income_source_system')
                config = plan(cost_bases=[declaration])
                p = portfolio(payment())
                before = copy.deepcopy((p, config))
                row = build(p, config)['yield_on_cost'][0]
                self.assertEqual(row['status'], status)
                self.assertEqual(row['coverage'], coverage)
                self.assertEqual(row['income_source_system'], declared_source)
                self.assertEqual((p, config), before)
                row['source']['reference'] = 'edited result evidence'
                self.assertEqual((p, config), before)

    def test_yield_missing_historical_attribution_is_unavailable_not_silently_omitted(self):
        for missing in ('holding_id', 'account_id'):
            a = payment()
            a.pop(missing)
            row = build(portfolio(a), plan(cost_bases=[cost()]))['yield_on_cost'][0]
            self.assertEqual(row['status'], 'unavailable')
            self.assertIn('scope', row['reason'].lower())

    def test_net_comparison_and_yield_use_received_metric_without_inventing_tax(self):
        config = plan(announcements=[announcement(amount_basis='net')], cost_bases=[cost(amount_basis='net')],
                      payment_links=[{'announcement_id': 'ann', 'activity_id': 'pay', 'source': source()}])
        p = portfolio(payment(metadata={'rikdom_income': {'version': 1, 'amount_basis': 'net'}}))
        result = build(p, config)
        self.assertEqual(result['reconciliation'][0]['received_amount'], 10)
        self.assertEqual(result['yield_on_cost'][0]['ratio'], .1)

    def test_dates_filter_declared_payment_dates_without_relabeling_cost_period(self):
        config = plan(announcements=[announcement('outside', payment_date='2025-12-31'), announcement()],
                      cost_bases=[cost()])
        result = build(portfolio(payment()), config, start='2026-01-01', end='2026-01-31')
        self.assertEqual([r['id'] for r in result['announced']], ['ann'])
        self.assertEqual(result['yield_on_cost'][0]['ratio'], .1)
        for bounds in ({'start': '20260101'}, {'start': '2026-02-30'},
                       {'start': '2026-02-01', 'end': '2026-01-01'}):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                build(config=config, **bounds)

    def test_input_validation_rejects_invalid_contracts_and_nonfinite_numbers(self):
        invalid = [None, [], {'version': True}, {'version': 2}, plan(extra=[]),
                   plan(announcements=[announcement(revision=True)]),
                   plan(announcements=[announcement(id=' ')]),
                   plan(announcements=[announcement(payment_date='2026-02-30')]),
                   plan(announcements=[announcement(scope={})]),
                   plan(announcements=[announcement(source=source(' '))]),
                   plan(announcements=[announcement(entitlement_quantity=2)]),
                   plan(cost_bases=[cost(period={'start': '2026-02-01', 'end': '2026-01-01'})]),
                   plan(cost_bases=[cost(method='market_value')]),
                   plan(cost_bases=[cost(money={'amount': 0, 'currency': 'USD'})])]
        for number in (True, float('inf'), float('nan'), '2', -1):
            invalid.append(plan(announcements=[announcement(money={'amount': number, 'currency': 'USD'})]))
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                build_income_planning_report(portfolio(), build_income_report(portfolio()), config)

    def test_received_report_cannot_supply_stale_or_foreign_financial_rows(self):
        p = portfolio(payment())
        received = build_income_report(p)
        received['events'][0]['gross'] = 900
        with self.assertRaisesRegex(ValueError, 'received'):
            build_income_planning_report(p, received, plan(cost_bases=[cost()]))

    def test_determinism_no_mutation_and_independent_output(self):
        p = portfolio(payment('b'), payment('a'))
        config = plan(announcements=[announcement()], cost_bases=[cost()])
        received = build_income_report(p)
        before = copy.deepcopy((p, received, config))
        result = build_income_planning_report(p, received, config)
        self.assertEqual((p, received, config), before)
        self.assertEqual(result, build_income_planning_report(p, received, config))
        json.dumps(result, allow_nan=False)
        result['announced'][0]['scope']['holding_id'] = 'changed'
        self.assertEqual((p, received, config), before)
