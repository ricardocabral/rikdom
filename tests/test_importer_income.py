from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
        import csv
        import io
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        return self.parse(plugin, stream.getvalue(), '.csv')[0]

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
