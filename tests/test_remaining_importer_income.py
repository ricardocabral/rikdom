"""Income evidence through the remaining first-party source pipelines."""
from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rikdom.import_preflight import build_preflight_report
from rikdom.income import build_income_report
from rikdom.instrument_performance import compute_instrument_performance
from tests.test_instrument_performance import _activity, _portfolio
from tests.test_btg_wm_conta_internacional_plugin import importer as btg_importer
from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities


class RemainingImporterIncomeTests(unittest.TestCase):
    def parse(self, plugin, content, suffix='.csv'):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ('income' + suffix)
            path.write_text(content, encoding='utf-8')
            first = run_import_pipeline(plugin, 'plugins', str(path))
            second = run_import_pipeline(plugin, 'plugins', str(path))
        self.assertEqual(first.get('activities'), second.get('activities'))
        portfolio = {'activities': [], 'holdings': []}
        merge_activities(portfolio, first)
        preflight = build_preflight_report(portfolio, second)
        self.assertTrue(preflight['ok'], preflight['issues'])
        _, counts = merge_activities(portfolio, second)
        self.assertEqual((counts.inserted, counts.updated), (0, 0))
        return first

    def broker_csv(self, plugin, action, amount, **fields):
        action_field = 'action' if plugin == 'fidelity' else 'activity_type'
        row = dict(record_type='transaction', account_number='A1', date='04/01/2026',
                   **{action_field: action}, amount=amount, currency='EUR')
        row.update(fields)
        return self.csv_rows(plugin, [row])

    def csv_rows(self, plugin, rows):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return self.parse(plugin, stream.getvalue())

    def income_event(self, payload):
        return build_income_report({'schema_version': '2.0.0', 'activities': payload['activities']})['events'][0]

    def test_broker_income_corrections_keep_sign_currency_fee_and_legacy_ids(self):
        ids = {'fidelity': ('1fe7d8d729e92d73', '5d74fe02b658216d'),
               'vanguard': ('133e1bca442b50d1', '13cff3a189ea6006')}
        for plugin in ids:
            for action, kind, digest in zip(('Cash Dividend', 'Credit Interest'),
                                             ('dividend', 'interest'), ids[plugin]):
                with self.subTest(plugin=plugin, action=action):
                    payload = self.broker_csv(plugin, action, -10, fees=-1)
                    row = payload['activities'][0]
                    self.assertEqual(row['money'], {'amount': -10, 'currency': 'EUR'})
                    self.assertEqual(row.get('fees'), {'amount': -1, 'currency': 'EUR'})
                    self.assertEqual(row['event_type'], kind)
                    self.assertEqual(row['id'], f'{plugin}-txn-a1-{digest}')
                    self.assertEqual(row['idempotency_key'], f'{plugin}:a1:{digest}')
                    self.assertEqual(row['metadata']['rikdom_income'], {'version': 1, 'amount_basis': 'unknown'})
                    self.assertEqual((self.income_event(payload)['gross'], self.income_event(payload)['net']), (None, None))

    def test_broker_tax_labels_and_refunds_are_signed_standalone_events(self):
        for plugin in ('fidelity', 'vanguard'):
            for action in ('Dividend Withholding Tax', 'Interest Withholding Tax', 'Tax', 'Tax Refund'):
                for amount in (-3, 2):
                    with self.subTest(plugin=plugin, action=action, amount=amount):
                        payload = self.broker_csv(plugin, action, amount)
                        row = payload['activities'][0]
                        self.assertEqual(row['event_type'], 'tax_withheld')
                        self.assertEqual(row['money']['amount'], amount)
                        self.assertEqual(build_income_report({'activities': payload['activities']})['events'], [])

    def test_broker_instrument_words_do_not_classify_as_tax(self):
        for plugin in ('fidelity', 'vanguard'):
            for action, kind in (('Tax-Exempt Bond dividend', 'dividend'),
                                 ('TAXF Credit Interest', 'interest'), ('Income', 'income')):
                with self.subTest(plugin=plugin, action=action):
                    row = self.broker_csv(plugin, action, -10)['activities'][0]
                    self.assertEqual(row['event_type'], kind)
                    self.assertEqual(row['money']['amount'], -10)

    def test_broker_explicit_zero_fee_is_retained_and_missing_is_absent(self):
        for plugin in ('fidelity', 'vanguard'):
            with self.subTest(plugin=plugin):
                self.assertEqual(self.broker_csv(plugin, 'Dividend', 10, fees=0)['activities'][0].get('fees'), {'amount': 0, 'currency': 'EUR'})
                self.assertNotIn('fees', self.broker_csv(plugin, 'Dividend', 10)['activities'][0])

    def test_broker_zero_income_is_reported_and_missing_amount_is_rejected(self):
        for plugin in ('fidelity', 'vanguard'):
            with self.subTest(plugin=plugin):
                self.assertEqual(self.broker_csv(plugin, 'Dividend', 0)['activities'][0]['money']['amount'], 0)
                with self.assertRaisesRegex(ValueError, 'amount'):
                    self.broker_csv(plugin, 'Dividend', '')

    def test_broker_signed_legacy_identity_collisions_cannot_drop_corrections(self):
        for plugin, action_field in (('fidelity', 'action'), ('vanguard', 'activity_type')):
            for reference in ('', 'source-1'):
                row = dict(record_type='transaction', account_number='A1', date='04/01/2026',
                           **{action_field: 'Dividend'}, amount=10, currency='USD', reference_id=reference)
                with self.subTest(plugin=plugin, reference=reference):
                    self.assertEqual(len(self.csv_rows(plugin, [row, row])['activities']), 1)
                    with self.assertRaisesRegex(ValueError, 'conflicting.*identity'):
                        self.csv_rows(plugin, [row, {**row, 'amount': -10}])

    def test_broker_reimport_cannot_overwrite_old_positive_normalized_money(self):
        for plugin in ('fidelity', 'vanguard'):
            with self.subTest(plugin=plugin):
                payload = self.broker_csv(plugin, 'Dividend', -10)
                legacy = copy.deepcopy(payload['activities'][0])
                legacy['money']['amount'] = 10
                legacy['metadata'].pop('rikdom_source_identity', None)
                legacy['metadata'].pop('rikdom_income', None)
                report = build_preflight_report({'holdings': [], 'activities': [legacy]}, payload)
                self.assertFalse(report['ok'])
                self.assertTrue(any(issue['code'] == 'AMBIGUOUS_IMPORT_IDENTITY' for issue in report['issues']))

    def test_explicit_invalid_broker_income_currency_cannot_be_relabelled(self):
        for plugin in ('fidelity', 'vanguard'):
            with self.subTest(plugin=plugin), self.assertRaisesRegex(ValueError, 'invalid.*currency'):
                self.broker_csv(plugin, 'Dividend', 10, currency='US')

    def test_source_keyed_broker_upgrade_conflicts_require_review(self):
        for plugin in ('fidelity', 'vanguard'):
            for action, amount in (('Dividend', -10), ('Dividend Withholding Tax', -3)):
                with self.subTest(plugin=plugin, action=action):
                    payload = self.broker_csv(plugin, action, amount, reference_id='source-1')
                    legacy = copy.deepcopy(payload['activities'][0])
                    legacy['money']['amount'] = abs(amount)
                    legacy['event_type'] = 'dividend'
                    legacy['metadata'].pop('rikdom_source_identity', None)
                    legacy['metadata'].pop('rikdom_income', None)
                    report = build_preflight_report({'holdings': [], 'activities': [legacy]}, payload)
                    self.assertFalse(report['ok'])
                    self.assertTrue(any(issue['code'] == 'AMBIGUOUS_IMPORT_IDENTITY' for issue in report['issues']))

    def test_broker_unknown_income_does_not_establish_instrument_return(self):
        for plugin in ('fidelity', 'vanguard'):
            with self.subTest(plugin=plugin):
                row = self.broker_csv(plugin, 'Dividend', 10, symbol='FII11')['activities'][0]
                row['holding_id'] = 'h-fii'
                portfolio = _portfolio(_activity(), row)
                portfolio['holdings'][0]['market_value'] = {'amount': 110, 'currency': 'EUR'}
                portfolio['holdings'][0]['as_of'] = '2026-05-01'
                portfolio['holdings'][0]['extensions']['rikdom_instrument_history']['through'] = '2026-05-01'
                portfolio['activities'][0]['money']['currency'] = 'EUR'
                result = compute_instrument_performance(portfolio, 'h-fii')
                self.assertEqual(result['status'], 'incomplete_history')
                self.assertIsNone(result['profit_amount'])
                self.assertTrue(any('basis' in message.lower() for message in result['warnings']))

    def ofx(self, amounts, *, fitid='source-1', kind='DIV', currency='EUR'):
        rows = ''.join(f'<INCOME><INVTRAN><FITID>{fitid}</FITID><DTTRADE>20260401</DTTRADE></INVTRAN><INCOMETYPE>{kind}</INCOMETYPE><TOTAL>{amount}</TOTAL></INCOME>' for amount in amounts)
        return self.parse('vanguard', f'<OFX><INVSTMTRS><ACCTID>A1</ACCTID><CURDEF>{currency}</CURDEF><INVTRANLIST>' + rows + '</INVTRANLIST></INVSTMTRS></OFX>', '.ofx')

    def test_vanguard_ofx_income_corrections_keep_sign_and_unknown_basis(self):
        for kind in ('DIV', 'INTEREST'):
            with self.subTest(kind=kind):
                payload = self.ofx([-10], kind=kind)
                row = payload['activities'][0]
                self.assertEqual(row['money'], {'amount': -10, 'currency': 'EUR'})
                self.assertEqual(row['id'], 'vanguard-txn-a1-source-1')
                self.assertEqual(row['metadata']['rikdom_income']['amount_basis'], 'unknown')
                self.assertEqual((self.income_event(payload)['gross'], self.income_event(payload)['net']), (None, None))

    def test_vanguard_ofx_explicit_invalid_currency_is_not_relabelled(self):
        with self.assertRaisesRegex(ValueError, 'invalid.*CURDEF'):
            self.ofx([10], currency='US')

    def test_vanguard_ofx_legacy_signed_reimport_requires_review(self):
        for fitid in ('source-1', ''):
            with self.subTest(fitid=fitid):
                payload = self.ofx([-10], fitid=fitid)
                legacy = copy.deepcopy(payload['activities'][0])
                legacy['money']['amount'] = 10
                legacy['metadata'].pop('rikdom_source_identity', None)
                legacy['metadata'].pop('rikdom_income', None)
                report = build_preflight_report({'activities': [legacy], 'holdings': []}, payload)
                self.assertFalse(report['ok'])

    def test_vanguard_ofx_conflicting_fitid_and_anonymous_signs_are_rejected(self):
        for fitid in ('source-1', ''):
            with self.subTest(fitid=fitid):
                self.assertEqual(len(self.ofx([10, 10], fitid=fitid)['activities']), 1)
                with self.assertRaisesRegex(ValueError, 'conflicting.*identity'):
                    self.ofx([10, -10], fitid=fitid)

    def test_vanguard_ofx_invalid_income_is_not_silently_dropped(self):
        for amount in ('NaN', 'Infinity', 'bad'):
            with self.subTest(amount=amount), self.assertRaisesRegex(ValueError, 'invalid.*TOTAL'):
                self.ofx([amount])

    def ibkr(self, rows):
        content = '<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1"><CashTransactions>' + rows + '</CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>'
        return self.parse('ibkr_flex_xml', content, '.xml')

    def test_ibkr_cash_income_cannot_assert_an_unreported_gross_basis(self):
        for kind in ('Dividends', 'Broker Interest Received'):
            for amount in (0, -10):
                with self.subTest(kind=kind, amount=amount):
                    payload = self.ibkr(f'<CashTransaction transactionID="cash-1" type="{kind}" amount="{amount}" currency="EUR" dateTime="20260401;120000"/>')
                    row = payload['activities'][0]
                    self.assertEqual(row['id'], 'ibkr-cash-cash-1')
                    self.assertEqual(row['money'], {'amount': amount, 'currency': 'EUR'})
                    self.assertEqual(row['metadata'].get('rikdom_income'), {'version': 1, 'amount_basis': 'unknown'})
                    self.assertEqual((self.income_event(payload)['gross'], self.income_event(payload)['net']), (None, None))
                    self.assertNotIn('withholding_tax', row)

    def test_ibkr_conflicting_cash_identity_cannot_drop_signed_correction(self):
        row = '<CashTransaction transactionID="cash-1" type="Dividends" amount="10" currency="EUR" dateTime="20260401;120000"/>'
        self.assertEqual(len(self.ibkr(row + row)['activities']), 1)
        for other in (row.replace('amount="10"', 'amount="-10"'), row.replace('currency="EUR"', 'currency="USD"')):
            with self.subTest(other=other), self.assertRaisesRegex(ValueError, 'conflicting.*identity'):
                self.ibkr(row + other)

    def test_btg_withholding_is_tax_and_income_basis_is_unknown(self):
        payload = self.parse('btg_wm_conta_internacional', Path('plugins/btg_wm_conta_internacional/fixtures/sample/input.txt').read_text(), '.txt')
        income = [a for a in payload['activities'] if a['metadata']['activity_type'] == 'DIV']
        taxes = [a for a in payload['activities'] if a['metadata']['activity_type'] == 'DIVNRA']
        self.assertEqual(len(income), 4)
        self.assertTrue(all(a['event_type'] == 'tax_withheld' for a in taxes))
        self.assertTrue(all(a['money']['amount'] < 0 for a in taxes))
        self.assertTrue(all(a['metadata']['rikdom_income']['amount_basis'] == 'unknown' for a in income))
        report = build_income_report({'activities': payload['activities']})
        self.assertEqual(len(report['events']), 4)
        self.assertTrue(all(a['gross'] is None and a['net'] is None for a in report['events']))

    def test_btg_signed_correction_and_tax_refund_preserve_cash_opening(self):
        prefix = Path('plugins/btg_wm_conta_internacional/fixtures/sample/input.txt').read_text().split('\nACTIVITY\n')[0]
        content = prefix + '''\nACTIVITY
04/03/2026 04/03/2026 USD DIV DWBDS - Dividend correction 0 0.00 (10.00)
04/03/2026 04/03/2026 USD DIVNRA DWBDS - NRA withholding refund 0 0.00 2.00
SWEEP ACTIVITY
CURRENT MONTH AGGREGATE INTEREST ACCRUED
'''
        payload = self.parse('btg_wm_conta_internacional', content, '.txt')
        rows = [a for a in payload['activities'] if a['instrument']['ticker'] == 'DWBDS']
        self.assertEqual([(a['event_type'], a['money']['amount']) for a in rows], [('transfer_in', 3210.79), ('dividend', -10), ('tax_withheld', 2)])
        self.assertEqual(btg_importer._period_deltas_for_ticker(rows[1:], 'DWBDS', enforce_cash_sign=True), (0, -8))
        legacy = copy.deepcopy(payload['activities'])
        for row in legacy:
            row['metadata'].pop('rikdom_source_identity', None)
            if row['metadata']['activity_type'] == 'DIVNRA':
                row['event_type'] = 'fee'
                row['subtype'] = 'withholding_tax'
        self.assertFalse(build_preflight_report({'activities': legacy, 'holdings': []}, payload)['ok'])

    def test_csv_generic_carries_explicit_basis_signed_and_zero_evidence(self):
        for basis, gross, net in (('gross', -10, -7), ('net', -13, -10), ('unknown', None, None)):
            with self.subTest(basis=basis):
                payload = self.csv_rows('csv-generic', [dict(record_type='activity', id='income-1', event_type='dividend', effective_at='2026-04-01T00:00:00Z', amount=-10, currency='EUR', amount_basis=basis, withholding_tax=-2, withholding_tax_currency='EUR', fees=-1, fees_currency='EUR')])
                row = payload['activities'][0]
                self.assertEqual(row.get('withholding_tax'), {'amount': -2, 'currency': 'EUR'})
                self.assertEqual(row.get('fees'), {'amount': -1, 'currency': 'EUR'})
                event = self.income_event(payload)
                self.assertEqual((event['gross'], event['net']), (gross, net))
        row = dict(record_type='activity', id='zero', event_type='interest', effective_at='2026-04-01T00:00:00Z', amount=10, currency='EUR', withholding_tax=0, fees=0)
        payload = self.csv_rows('csv-generic', [row])
        self.assertEqual(self.income_event(payload)['net'], 10)
        payload = self.csv_rows('csv-generic', [{k: v for k, v in row.items() if k not in ('withholding_tax', 'fees')}])
        self.assertEqual(self.income_event(payload)['gross'], 10)
        self.assertIsNone(self.income_event(payload)['net'])

    def test_csv_generic_preserves_charge_currencies_and_rejects_invalid_evidence(self):
        row = dict(record_type='activity', id='income-1', event_type='dividend', effective_at='2026-04-01T00:00:00Z', amount=10, currency='EUR', amount_basis='net', withholding_tax=2, withholding_tax_currency='USD', fees=0, fees_currency='GBP')
        payload = self.csv_rows('csv-generic', [row])
        self.assertEqual(payload['activities'][0]['withholding_tax']['currency'], 'USD')
        self.assertEqual(payload['activities'][0]['fees']['currency'], 'GBP')
        self.assertIsNone(self.income_event(payload)['gross'])
        for field, invalid in (('amount_basis', 'guess'), ('withholding_tax', 'NaN'), ('fees', 'bad'), ('fees_currency', 'US')):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Invalid|invalid'):
                self.csv_rows('csv-generic', [{**row, field: invalid}])

    def test_holdings_only_sources_do_not_create_received_income(self):
        for plugin, fixture in (('irpf-xml', 'plugins/irpf-xml/fixtures/sample/input.xml'),
                                ('btg-investment-pdf', 'plugins/btg-investment-pdf/fixtures/default/input.txt'),
                                ('b3-consolidado-mensal', 'plugins/b3-consolidado-mensal/fixtures/acoes_minimal/input.xlsx')):
            with self.subTest(plugin=plugin):
                payload = run_import_pipeline(plugin, 'plugins', fixture)
                self.assertEqual(payload.get('activities', []), [])
                self.assertEqual(build_income_report({'activities': payload.get('activities', [])})['events'], [])
                coverage = payload['metadata']['rikdom_import_diagnostics']['history_coverage']
                self.assertTrue(all(row['status'] == 'unknown' and row['event_types'] == [] for row in coverage))

    def test_normalized_json_preserves_canonical_income_evidence(self):
        row = dict(id='normalized-income', event_type='dividend', status='posted', effective_at='2026-04-01T00:00:00Z', money={'amount': -10, 'currency': 'EUR'}, withholding_tax={'amount': 0, 'currency': 'EUR'}, metadata={'rikdom_income': {'version': 1, 'amount_basis': 'net'}, 'custom': 'keep'})
        payload = self.parse('normalized-statement-json', json.dumps({'provider': 'manual', 'generated_at': '2026-04-02T00:00:00Z', 'activities': [row]}), '.json')
        self.assertEqual(payload['activities'], [row])
        self.assertEqual((self.income_event(payload)['gross'], self.income_event(payload)['net']), (-10, -10))


if __name__ == '__main__':
    unittest.main()
