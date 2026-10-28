from __future__ import annotations

import csv
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.income import build_income_report
from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities


class ImporterIncomeTests(unittest.TestCase):
    def parse(self, plugin, content, suffix):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ('income' + suffix)
            path.write_text(content, encoding='utf-8')
            first = run_import_pipeline(plugin, 'plugins', str(path))
            second = run_import_pipeline(plugin, 'plugins', str(path))
        self.assertEqual(first['activities'], second['activities'])
        portfolio = {'activities': [], 'holdings': []}
        merge_activities(portfolio, first)
        _, counts = merge_activities(portfolio, second)
        self.assertEqual(counts.inserted, 0)
        self.assertEqual(len(portfolio['activities']), len(first['activities']))
        return first['activities']

    def pp(self, row):
        return self.parse('portfolio_performance_csv',
            'Date,Type,Value,Transaction Currency,Gross Amount,Currency Gross Amount,Fees,Currency Fees,Taxes,Currency Taxes\n' + row + '\n', '.csv')[0]

    def wealthfolio(self, plugin, kind, **fields):
        row = dict(id='income-1', date='2026-04-01', activity_type=kind,
                   currency='USD', **fields)
        if plugin == 'wealthfolio_export_json':
            return self.parse(plugin, json.dumps({'activities': [row]}), '.json')[0]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        return self.parse(plugin, stream.getvalue(), '.csv')[0]

    def schwab(self, action, amount, **fields):
        row = dict(record_type='transaction', account_number='A1', action=action,
                   amount=amount, date='04/01/2026', currency='USD',
                   description='Tax-Exempt Bond', symbol='TAXF', **fields)
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        return self.parse('charles-schwab', stream.getvalue(), '.csv')[0]

    def ghostfolio(self, kind='DIVIDEND', **fields):
        row = dict(date='2026-04-01', type=kind, currency='USD', **fields)
        return self.parse('ghostfolio_export_json', json.dumps({'activities': [row]}), '.json')[0]

    def test_schwab_income_corrections_preserve_signed_cash_and_legacy_identity(self):
        for kind, event_type, suffix in (
                ('Cash Dividend', 'dividend', '65ac75f1f89188af'),
                ('Credit Interest', 'interest', '89926acb1547e4b8')):
            with self.subTest(kind=kind):
                row = self.schwab(kind, -10, fees=-1)
                self.assertEqual(row['money'], {'amount': -10, 'currency': 'USD'})
                self.assertEqual(row['event_type'], event_type)
                self.assertEqual(row['fees'], {'amount': -1, 'currency': 'USD'})
                self.assertEqual(row['id'], 'schwab-txn-a1-' + suffix)
                self.assertEqual(row['idempotency_key'], 'schwab:a1:' + suffix)
                self.assertEqual(row['metadata'].get('rikdom_income'), {'version': 1, 'amount_basis': 'unknown'})
                self.assertNotIn('withholding_tax', row)
                report = build_income_report({'schema_version': '2.0.0', 'activities': [row]})
                self.assertEqual((report['events'][0]['gross'], report['events'][0]['net']), (None, None))

    def test_schwab_explicit_tax_labels_precede_dividend_interest_and_keep_refunds(self):
        for kind in ('Dividend Withholding Tax', 'Interest Withholding Tax', 'Tax', 'Tax Refund'):
            for amount in (-10, 2):
                with self.subTest(kind=kind, amount=amount):
                    row = self.schwab(kind, amount, fees=-1)
                    self.assertEqual(row['event_type'], 'tax_withheld')
                    self.assertEqual(row['money']['amount'], amount)
                    self.assertEqual(build_income_report({'schema_version': '2.0.0', 'activities': [row]})['events'], [])
                    if kind == 'Dividend Withholding Tax' and amount == -10:
                        self.assertEqual(row['id'], 'schwab-txn-a1-d5d92779c549026e')

    def test_schwab_bounded_source_labels_do_not_classify_instrument_words_as_tax(self):
        for kind, expected in (('Cash Dividend', 'dividend'), ('Credit Interest', 'interest'),
                               ('TAXF Cash Dividend', 'dividend'), ('Tax-Exempt Bond dividend', 'dividend'),
                               ('TAXF cash adjustment', 'other'), ('Tax-Exempt Bond', 'other'),
                               ('Income', 'income')):
            with self.subTest(kind=kind):
                row = self.schwab(kind, -10)
                self.assertEqual(row['event_type'], expected)
                self.assertEqual(row['money']['amount'], -10)

    def test_schwab_legacy_identity_collision_cannot_drop_signed_correction(self):
        header = 'record_type,account_number,date,action,amount,currency\n'
        positive = 'transaction,A1,04/01/2026,Cash Dividend,10,USD\n'
        negative = 'transaction,A1,04/01/2026,Cash Dividend,-10,USD\n'
        self.assertEqual(len(self.parse('charles-schwab', header + positive + positive, '.csv')), 1)
        with self.assertRaisesRegex(ValueError, 'conflicting.*identity'):
            self.parse('charles-schwab', header + positive + negative, '.csv')

    def test_schwab_explicit_zero_income_fee_is_retained(self):
        row = self.schwab('Cash Dividend', 10, fees=0)
        self.assertEqual(row['fees'], {'amount': 0, 'currency': 'USD'})
        self.assertNotIn('fees', self.schwab('Cash Dividend', 10))

    def test_ghostfolio_explicit_amount_aliases_drive_income_rollup(self):
        for field, amount, tax, fee, gross, net in (
                ('netAmount', 85, 15, 0, 100, 85),
                ('grossAmount', 100, 15, 1, 100, 84),
                ('netAmount', -85, -15, -1, -101, -85),
                ('grossAmount', -100, -15, -1, -100, -84)):
            with self.subTest(field=field, amount=amount):
                row = self.ghostfolio(**{field: amount, 'tax': tax, 'fee': fee})
                self.assertEqual(row['money'], {'amount': amount, 'currency': 'USD'})
                self.assertEqual(row['withholding_tax'], {'amount': tax, 'currency': 'USD'})
                self.assertEqual(row['fees'], {'amount': fee, 'currency': 'USD'})
                report = build_income_report({'schema_version': '2.0.0', 'activities': [row]})
                self.assertEqual((report['events'][0]['gross'], report['events'][0]['net']), (gross, net))
                self.assertEqual(report['monthly'][0]['gross']['total'], gross)
                self.assertEqual(report['yearly'][0]['net']['total'], net)
                if field == 'netAmount' and amount == 85:
                    self.assertEqual(row['id'], 'ghostfolio-act-fd8a3f70016c8989')

    def test_ghostfolio_ambiguous_amount_aliases_keep_unknown_basis(self):
        for field in ('amount', 'value'):
            for kind in ('DIVIDEND', 'INTEREST', 'INCOME'):
                with self.subTest(field=field, kind=kind):
                    row = self.ghostfolio(kind, **{field: -10})
                    self.assertEqual(row['event_type'], kind.lower())
                    self.assertEqual(row['metadata'].get('rikdom_income'), {'version': 1, 'amount_basis': 'unknown'})
                    if kind != 'INCOME':
                        report = build_income_report({'schema_version': '2.0.0', 'activities': [row]})
                        self.assertEqual((report['events'][0]['gross'], report['events'][0]['net']), (None, None))

    def test_ghostfolio_tax_events_and_refunds_remain_separate_signed_events(self):
        for kind, amount in (('TAX', -15), ('TAX_REFUND', 2), ('WITHHOLDING_TAX', -3)):
            with self.subTest(kind=kind):
                row = self.ghostfolio(kind, amount=amount)
                self.assertEqual(row['event_type'], 'tax_withheld')
                self.assertEqual(row['money']['amount'], amount)
                self.assertEqual(build_income_report({'schema_version': '2.0.0', 'activities': [row]})['events'], [])

    def test_ghostfolio_zero_withholding_is_evidence_missing_is_unknown(self):
        zero = self.ghostfolio(grossAmount=10, withholdingTax=0, fee=0)
        missing = self.ghostfolio(grossAmount=10)
        self.assertEqual(zero['withholding_tax'], {'amount': 0, 'currency': 'USD'})
        self.assertNotIn('withholding_tax', missing)
        for row, net in ((zero, 10), (missing, None)):
            report = build_income_report({'schema_version': '2.0.0', 'activities': [row]})
            self.assertEqual(report['events'][0]['net'], net)

    def test_ghostfolio_attached_charges_retain_source_currencies(self):
        row = self.ghostfolio(netAmount=85, withholdingTax=15, withholdingTaxCurrency='EUR',
                              fee=-1, feeCurrency='GBP')
        self.assertEqual(row['withholding_tax'], {'amount': 15, 'currency': 'EUR'})
        self.assertEqual(row['fees'], {'amount': -1, 'currency': 'GBP'})
        report = build_income_report({'schema_version': '2.0.0', 'activities': [row]})
        self.assertEqual((report['events'][0]['gross'], report['events'][0]['net']), (None, 85))
        self.assertTrue(report['events'][0]['diagnostics'])

    def test_ghostfolio_money_objects_retain_their_own_currencies(self):
        row = self.ghostfolio(grossAmount={'amount': -10, 'currency': 'EUR'},
                              fees={'amount': -1, 'currency': 'GBP'},
                              withholding_tax={'amount': -2, 'currency': 'CHF'})
        self.assertEqual(row['money'], {'amount': -10, 'currency': 'EUR'})
        self.assertEqual(row['fees'], {'amount': -1, 'currency': 'GBP'})
        self.assertEqual(row['withholding_tax'], {'amount': -2, 'currency': 'CHF'})

    def test_ghostfolio_explicit_invalid_monetary_evidence_cannot_be_dropped(self):
        for field in ('amount', 'value', 'netAmount', 'grossAmount', 'fee', 'fees', 'feeAmount',
                      'tax', 'withholdingTax', 'withholding_tax'):
            for invalid in ('NaN', 'Infinity', 'bad', True, {'amount': 'bad', 'currency': 'USD'}):
                with self.subTest(field=field, invalid=invalid):
                    fields = dict(amount=85, netAmount=85, grossAmount=100)
                    fields[field] = invalid
                    with self.assertRaisesRegex(ValueError, 'invalid'):
                        self.ghostfolio(**fields)

    def test_ghostfolio_explicit_invalid_charge_currency_cannot_be_relabelled(self):
        for fields in (dict(fee=1, feeCurrency='US'), dict(tax=1, taxCurrency='US'),
                       dict(fee={'amount': 1, 'currency': 'US'})):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, 'currency'):
                self.ghostfolio(netAmount=85, **fields)

    def test_ghostfolio_amount_and_charges_need_source_currency_evidence(self):
        for fields in (dict(netAmount=85), dict(grossAmount={'amount': 85}, tax=15),
                       dict(netAmount={'amount': 85, 'currency': 'EUR'}, tax=15),
                       dict(netAmount={'amount': 85, 'currency': 'EUR'}, fee=1)):
            with self.subTest(fields=fields):
                row = dict(date='2026-04-01', type='DIVIDEND', **fields)
                with self.assertRaisesRegex(ValueError, 'currency'):
                    self.parse('ghostfolio_export_json', json.dumps({'activities': [row]}), '.json')

    def test_ibkr_dividend_labelled_withholding_and_refund_stay_separate_signed_tax(self):
        rows = self.parse('ibkr_flex_xml', '''<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1" whenGenerated="20260421;150000"><CashTransactions>
          <CashTransaction transactionID="div" type="Dividends" description="AAPL dividend" amount="10" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="tax" type="Withholding Tax" description="AAPL dividend withholding" amount="-3" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="refund" type="Withholding Tax" description="Interest withholding refund" amount="1" currency="USD" dateTime="20260420;120000"/>
        </CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>''', '.xml')
        by_id = {a['id']: a for a in rows}
        self.assertEqual(by_id['ibkr-cash-tax']['event_type'], 'tax_withheld')
        self.assertEqual(by_id['ibkr-cash-tax']['money']['amount'], -3)
        self.assertEqual(by_id['ibkr-cash-refund']['event_type'], 'tax_withheld')
        self.assertEqual(by_id['ibkr-cash-refund']['money']['amount'], 1)
        self.assertNotIn('withholding_tax', by_id['ibkr-cash-div'])
        self.assertEqual(by_id['ibkr-cash-div']['money']['amount'], 10)

    def test_ibkr_recognized_source_type_precedes_instrument_description(self):
        rows = self.parse('ibkr_flex_xml', '''<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1" whenGenerated="20260421;150000"><CashTransactions>
          <CashTransaction transactionID="taxf" type="Dividends" description="TAXF Cash Dividend USD 0.10 per Share (Ordinary Dividend)" amount="10" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="exempt" type="Dividends" description="Tax-Exempt Bond dividend" amount="10" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="interest" type="Broker Interest Received" description="TAXF interest" amount="2" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="withholding" type="Withholding Tax" description="AAPL dividend" amount="-3" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="interest-tax" type="Withholding Tax" description="Broker interest" amount="-1" currency="USD" dateTime="20260420;120000"/>
        </CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>''', '.xml')
        self.assertEqual({row['id']: row['event_type'] for row in rows}, {
            'ibkr-cash-taxf': 'dividend', 'ibkr-cash-exempt': 'dividend',
            'ibkr-cash-interest': 'interest', 'ibkr-cash-withholding': 'tax_withheld',
            'ibkr-cash-interest-tax': 'tax_withheld',
        })
        self.assertEqual(next(row for row in rows if row['id'] == 'ibkr-cash-withholding')['money']['amount'], -3)

    def test_ibkr_unclassified_type_uses_bounded_description_fallback(self):
        rows = self.parse('ibkr_flex_xml', '''<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1" whenGenerated="20260421;150000"><CashTransactions>
          <CashTransaction transactionID="taxf" type="Adjustment" description="TAXF Cash Dividend USD 0.10 per Share" amount="10" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="exempt" type="Adjustment" description="Tax-Exempt Bond dividend" amount="10" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="withholding" type="Adjustment" description="AAPL dividend withholding tax" amount="-3" currency="USD" dateTime="20260420;120000"/>
          <CashTransaction transactionID="ticker" type="Adjustment" description="TAXF cash adjustment" amount="1" currency="USD" dateTime="20260420;120000"/>
        </CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>''', '.xml')
        self.assertEqual({row['id']: row['event_type'] for row in rows}, {
            'ibkr-cash-taxf': 'dividend', 'ibkr-cash-exempt': 'dividend',
            'ibkr-cash-withholding': 'tax_withheld', 'ibkr-cash-ticker': 'other',
        })

    def test_pp_gross_only_buy_keeps_existing_outflow_convention(self):
        row = self.pp('2026-04-01,Buy,,EUR,10,EUR,,,,')
        self.assertEqual(row['event_type'], 'buy')
        self.assertEqual(row['money'], {'amount': -10, 'currency': 'EUR'})

    def test_wealthfolio_csv_new_tax_evidence_preserves_existing_anonymous_id(self):
        row = self.parse('wealthfolio_activity_csv',
            'date,activity_type,amount,currency,fee,tax\n2026-04-01,DIVIDEND,84,USD,1,15\n', '.csv')[0]
        self.assertEqual(row['id'], 'wealthfolio-csv-wf-csv-c8637015c5244181')
        self.assertEqual(row['withholding_tax']['amount'], 15)

    def test_pp_net_value_keeps_withholding_fees_and_gross_evidence(self):
        row = self.pp('2026-04-01,Dividend,7,EUR,10,EUR,1,EUR,2,EUR')
        self.assertEqual(row['money'], {'amount': 7, 'currency': 'EUR'})
        self.assertEqual(row['metadata']['rikdom_income'], {'version': 1, 'amount_basis': 'net'})
        self.assertEqual(row['withholding_tax'], {'amount': 2, 'currency': 'EUR'})
        self.assertEqual(row['fees'], {'amount': 1, 'currency': 'EUR'})
        self.assertEqual(row['metadata']['source_money']['gross_amount'], '10')

    def test_pp_cross_currency_amounts_are_never_relabelled_or_converted(self):
        row = self.pp('2026-04-01,Dividend,7,EUR,12,USD,1,GBP,2,USD')
        self.assertEqual(row['money'], {'amount': 7, 'currency': 'EUR'})
        self.assertEqual(row['metadata']['rikdom_income']['amount_basis'], 'net')
        self.assertEqual(row['withholding_tax'], {'amount': 2, 'currency': 'USD'})
        self.assertEqual(row['fees'], {'amount': 1, 'currency': 'GBP'})
        self.assertEqual(row['metadata']['source_money']['gross_currency'], 'USD')

    def test_pp_gross_only_uses_own_currency_and_preserves_signed_adjustments(self):
        row = self.pp('2026-04-01,Interest,,EUR,-10,USD,-1,USD,-2,USD')
        self.assertEqual(row['money'], {'amount': -10, 'currency': 'USD'})
        self.assertEqual(row['metadata']['rikdom_income']['amount_basis'], 'gross')
        self.assertEqual(row['withholding_tax']['amount'], -2)
        self.assertEqual(row['fees']['amount'], -1)

    def test_pp_gross_without_own_currency_is_not_assumed_transaction_currency(self):
        with self.assertRaisesRegex(ValueError, 'Gross Amount.*currency'):
            self.pp('2026-04-01,Dividend,,EUR,10,,,,,')

    def test_pp_explicit_zero_tax_is_evidence_and_absence_is_unknown(self):
        zero = self.pp('2026-04-01,Dividend,10,EUR,10,EUR,0,EUR,0,EUR')
        missing = self.pp('2026-04-01,Dividend,10,EUR,10,EUR,,,,')
        self.assertEqual(zero['withholding_tax'], {'amount': 0, 'currency': 'EUR'})
        self.assertNotIn('withholding_tax', missing)

    def test_wealthfolio_generic_income_is_not_a_dividend(self):
        for plugin in ('wealthfolio_activity_csv', 'wealthfolio_export_json'):
            with self.subTest(plugin=plugin):
                row = self.wealthfolio(plugin, 'INCOME', amount=-10)
                self.assertEqual(row['event_type'], 'income')
                self.assertEqual(row['money']['amount'], -10)

    def test_wealthfolio_tax_and_refund_keep_signed_money(self):
        for plugin in ('wealthfolio_activity_csv', 'wealthfolio_export_json'):
            for kind, amount in (('TAX', -3), ('TAX_REFUND', 1)):
                with self.subTest(plugin=plugin, kind=kind):
                    row = self.wealthfolio(plugin, kind, amount=amount)
                    self.assertEqual(row['event_type'], 'tax_withheld')
                    self.assertEqual(row['money']['amount'], amount)

    def test_wealthfolio_explicit_income_is_net_and_preserves_attached_tax_and_fee(self):
        for plugin in ('wealthfolio_activity_csv', 'wealthfolio_export_json'):
            with self.subTest(plugin=plugin):
                row = self.wealthfolio(plugin, 'DIVIDEND', amount=84, tax=15, fee=1)
                self.assertEqual(row['money'], {'amount': 84, 'currency': 'USD'})
                self.assertEqual(row['metadata']['rikdom_income']['amount_basis'], 'net')
                self.assertEqual(row['withholding_tax'], {'amount': 15, 'currency': 'USD'})
                self.assertEqual(row['fees'], {'amount': 1, 'currency': 'USD'})

    def test_wealthfolio_json_net_amount_alias_is_marked_net(self):
        row = self.wealthfolio('wealthfolio_export_json', 'INTEREST', net_amount=-4, tax=-1, fee=-0.5)
        self.assertEqual(row['money']['amount'], -4)
        self.assertEqual(row['metadata']['rikdom_income']['amount_basis'], 'net')
        self.assertEqual(row['withholding_tax']['amount'], -1)
        self.assertEqual(row['fees']['amount'], -0.5)

    def test_wealthfolio_legacy_derived_income_has_unknown_basis(self):
        for plugin in ('wealthfolio_activity_csv', 'wealthfolio_export_json'):
            with self.subTest(plugin=plugin):
                row = self.wealthfolio(plugin, 'INTEREST', quantity=2, unit_price=10)
                self.assertEqual(row['money']['amount'], 20)
                self.assertEqual(row['metadata']['rikdom_income']['amount_basis'], 'unknown')

    def test_malformed_income_money_is_not_silently_replaced_or_dropped(self):
        for field in ('value', 'gross', 'fees', 'taxes'):
            cells = ['2026-04-01', 'Dividend', '7', 'EUR', '10', 'EUR', '1', 'EUR', '2', 'EUR']
            cells[{'value': 2, 'gross': 4, 'fees': 6, 'taxes': 8}[field]] = 'NaN'
            with self.subTest(plugin='pp', field=field):
                with self.assertRaisesRegex(ValueError, 'invalid'):
                    self.pp(','.join(cells))
        for plugin in ('wealthfolio_activity_csv', 'wealthfolio_export_json'):
            for field in ('amount', 'tax', 'fee'):
                with self.subTest(plugin=plugin, field=field):
                    fields = dict(amount=7, quantity=1, unit_price=10)
                    fields[field] = 'Infinity'
                    with self.assertRaisesRegex(ValueError, 'invalid'):
                        self.wealthfolio(plugin, 'DIVIDEND', **fields)


if __name__ == '__main__':
    unittest.main()
