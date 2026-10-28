import copy
import json
import unittest

from rikdom import income


def event(aid='a', amount=100, currency='USD', date='2026-01-01T00:00:00Z', **fields):
    return {'id': aid, 'event_type': 'dividend', 'status': 'posted', 'effective_at': date,
            'money': {'amount': amount, 'currency': currency}, **fields}


def portfolio(*events):
    return {'schema_version': '2.0.0', 'activities': list(events)}


def correction(aid, target, **fields):
    return event(aid, extensions={'rikdom_correction': {
        'version': 1, 'supersedes_activity_id': target, 'reason': 'Source correction'}}, **fields)


class IncomeTests(unittest.TestCase):
    def test_periods_currencies_partial_totals_and_signed_adjustments(self):
        p = portfolio(
            event('a', 100, withholding_tax={'amount': 10, 'currency': 'USD'},
                  fees={'amount': 2, 'currency': 'USD'}),
            event('b', 20),
            event('c', -5, withholding_tax={'amount': -1, 'currency': 'USD'}),
            event('d', 30, 'EUR', event_type='interest'),
            event('e', 7, date='2026-02-01T00:00:00Z'),
            event('f', 9, date='2025-12-31T23:30:00-03:00'),
        )
        report = income.build_income_report(p)
        self.assertEqual([(b['period'], b['currency'], b['event_count']) for b in report['monthly']],
                         [('2025-12', 'USD', 1), ('2026-01', 'EUR', 1),
                          ('2026-01', 'USD', 3), ('2026-02', 'USD', 1)])
        jan = report['monthly'][2]
        self.assertEqual(jan['gross'], {'total': 115, 'known_subtotal': 115, 'unavailable_count': 0})
        self.assertEqual(jan['withholding'], {'total': None, 'known_subtotal': 9, 'unavailable_count': 1})
        self.assertEqual(jan['net'], {'total': None, 'known_subtotal': 84, 'unavailable_count': 1})
        self.assertEqual(report['yearly'][2]['gross']['total'], 122)
        self.assertEqual([r['activity_id'] for r in report['events']], ['f', 'a', 'b', 'c', 'd', 'e'])
        json.dumps(report, allow_nan=False)

    def test_amount_basis_zero_tax_fees_and_unknowns(self):
        cases = [
            ({}, 100, None),
            ({'withholding_tax': {'amount': 0, 'currency': 'USD'}}, 100, 100),
            ({'metadata': {'rikdom_income': {'version': 1, 'amount_basis': 'net'}}}, None, 100),
            ({'metadata': {'rikdom_income': {'version': 1, 'amount_basis': 'net'}},
              'withholding_tax': {'amount': 10, 'currency': 'USD'},
              'fees': {'amount': 2, 'currency': 'USD'}}, 112, 100),
            ({'metadata': {'rikdom_income': {'version': 1, 'amount_basis': 'unknown'}},
              'withholding_tax': {'amount': 0, 'currency': 'USD'}}, None, None),
        ]
        for fields, gross, net in cases:
            with self.subTest(fields=fields):
                row = income.build_income_report(portfolio(event(**fields)))['events'][0]
                self.assertEqual((row['gross'], row['net']), (gross, net))

    def test_cross_currency_charges_are_unavailable_and_diagnosed(self):
        cases = [
            {'fees': {'amount': 2, 'currency': 'EUR'},
             'withholding_tax': {'amount': 0, 'currency': 'USD'}},
            {'withholding_tax': {'amount': 2, 'currency': 'EUR'}},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                row = income.build_income_report(portfolio(event(**fields)))['events'][0]
                self.assertIsNone(row['net'])
                self.assertTrue(any('currency' in d.lower() for d in row['diagnostics']))
                self.assertEqual(row['gross'], 100)

    def test_legacy_unknown_basis_is_respected_and_modern_marker_is_authoritative(self):
        row = income.build_income_report(portfolio(event(metadata={
            'amount_basis': 'reported_gross_net_unknown'})))['events'][0]
        self.assertEqual((row['amount_basis'], row['gross'], row['net']), ('unknown', None, None))
        self.assertTrue(row['diagnostics'])
        row = income.build_income_report(portfolio(event(metadata={
            'amount_basis': 'reported_gross_net_unknown',
            'rikdom_income': {'version': 1, 'amount_basis': 'net'}})))['events'][0]
        self.assertEqual(row['net'], 100)

    def test_overflow_is_rejected_instead_of_emitting_infinite_subtotals(self):
        with self.assertRaisesRegex(ValueError, 'finite'):
            income.build_income_report(portfolio(event('a', 1e308), event('b', 1e308)))

    def test_invalid_explicit_offset_is_rejected(self):
        with self.assertRaises(ValueError):
            income.build_income_report(portfolio(event(date='2026-01-01T00:00:00+00:99')))

    def test_projection_precedes_event_status_and_date_filters(self):
        rows = [event('a'), correction('b', 'a', amount=50), correction('c', 'b', event_type='buy'),
                event('d'), correction('e', 'd', status='cancelled'),
                event('pending', status='pending'), event('cancelled', status='cancelled'),
                event('reinvest', event_type='buy'), event('generic', event_type='income'),
                event('principal', event_type='amortization'),
                event('interest', event_type='interest'), event('old', date='2025-12-31T23:30:00-03:00')]
        report = income.build_income_report(portfolio(*rows), start='2026-01-01', end='2026-01-01')
        self.assertEqual([r['activity_id'] for r in report['events']], ['interest'])
        replacement = correction('next-year', 'a', date='2027-01-01T00:00:00Z')
        self.assertEqual(income.build_income_report(portfolio(event('a'), replacement), end='2026-12-31')['events'], [])

    def test_asserted_dimensions_determinism_and_no_mutation(self):
        a = event('a', account_id='account', asset_type_id='stock', holding_id='holding', instrument={'ticker': 'ABC'})
        b = event('b')
        p = portfolio(b, a)
        before = copy.deepcopy(p)
        report = income.build_income_report(p)
        self.assertEqual(report, income.build_income_report(portfolio(a, b)))
        self.assertEqual(p, before)
        self.assertEqual(report['events'][0]['instrument'], {'ticker': 'ABC'})
        self.assertEqual(report['events'][0]['account_id'], 'account')
        self.assertIsNone(report['events'][1]['account_id'])
        self.assertIsNone(report['events'][1]['asset_type_id'])
        report['events'][0]['instrument']['ticker'] = 'changed'
        self.assertEqual(p, before)

    def test_invalid_values_dates_and_metadata_rejected(self):
        bad = [event(money=None), event(effective_at=None), event(effective_at='not-date'),
               event(effective_at='2026-02-30T00:00:00Z'), event(effective_at='2026-01-01T00:00:00'),
               event(money={'amount': 1, 'currency': 'US'}),
               event(metadata={'rikdom_income': {'version': True, 'amount_basis': 'gross'}}),
               event(metadata={'rikdom_income': {'version': 1, 'amount_basis': 'cash'}})]
        for amount in (True, float('nan'), float('inf'), -float('inf'), '10'):
            bad.append(event(amount=amount))
            bad.append(event(fees={'amount': amount, 'currency': 'USD'}))
            bad.append(event(withholding_tax={'amount': amount, 'currency': 'USD'}))
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                income.build_income_report(portfolio(row))
        for start, end in [('20260101', None), ('bad', None), ('2026-02-01', '2026-01-01')]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                income.build_income_report(portfolio(), start=start, end=end)

    def test_contract_is_checked_and_empty_history_supported(self):
        with self.assertRaises(ValueError):
            income.build_income_report({'schema_version': '99.0.0'})
        with self.assertRaises(ValueError):
            income.build_income_report(portfolio(correction('bad', 'missing')))
        report = income.build_income_report(portfolio())
        self.assertEqual((report['events'], report['monthly'], report['yearly']), ([], [], []))

    def test_malformed_ledger_or_duplicate_identities_fail_visibly(self):
        for activities in ({'a': event()}, [None], [event(), event()],
                           [event('a', idempotency_key='same'), event('b', idempotency_key='same')],
                           [{k: v for k, v in event().items() if k != 'id'}]):
            with self.subTest(activities=activities), self.assertRaises(ValueError):
                income.build_income_report({'schema_version': '2.0.0', 'activities': activities})

    def test_received_income_requires_explicit_valid_status(self):
        for row in ({k: v for k, v in event().items() if k != 'status'},
                    event(status='settled'), event(status=None)):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'status'):
                income.build_income_report(portfolio(row))
