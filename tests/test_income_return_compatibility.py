"""Income source amount-basis changes preserve investor receipt calculations."""
import unittest

from rikdom.instrument_performance import compute_instrument_performance
from test_instrument_performance import _activity, _portfolio


class IncomeReturnCompatibilityTests(unittest.TestCase):
    def test_net_distribution_does_not_deduct_reported_costs_twice(self):
        dividend = _activity(
            'dividend', 85, id='div', when='2026-01-01',
            fees={'amount': 5, 'currency': 'BRL'},
            withholding_tax={'amount': 10, 'currency': 'BRL'},
            metadata={'rikdom_income': {'version': 1, 'amount_basis': 'net'}},
        )
        result = compute_instrument_performance(_portfolio(_activity(), dividend), 'h-fii')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['observed_distributions'], 85)
        self.assertEqual(result['observed_fees'], 5)
        self.assertEqual(result['observed_taxes'], 10)
        self.assertEqual(result['profit_amount'], 95)

    def test_explicit_unknown_distribution_does_not_establish_full_return(self):
        for metadata in (
            {'rikdom_income': {'version': 1, 'amount_basis': 'unknown'}},
            {'amount_basis': 'reported_gross_net_unknown'},
            {'rikdom_income': {'version': True, 'amount_basis': 'net'}},
        ):
            with self.subTest(metadata=metadata):
                dividend = _activity('dividend', 85, id='div', when='2026-01-01', metadata=metadata)
                result = compute_instrument_performance(_portfolio(_activity(), dividend), 'h-fii')
                self.assertEqual(result['status'], 'incomplete_history')
                self.assertIsNone(result['profit_amount'])
                self.assertIsNone(result['xirr_pct'])
                self.assertTrue(any('income' in w.lower() or 'basis' in w.lower() for w in result['warnings']))


    def test_net_receipt_survives_unavailable_foreign_charge_breakdown(self):
        dividend = _activity('dividend', 85, id='div', when='2026-01-01',
                             withholding_tax={'amount': 10, 'currency': 'USD'},
                             metadata={'rikdom_income': {'version': 1, 'amount_basis': 'net'}})
        result = compute_instrument_performance(_portfolio(_activity(), dividend), 'h-fii')
        self.assertEqual(result['observed_distributions'], 85)
        self.assertEqual(result['observed_net_cashflow'], -15)
        self.assertTrue(any('USD' in w for w in result['warnings']))

    def test_net_receipt_and_reported_tax_refund_remain_signed(self):
        for amount, tax in ((85, -5), (-5, 0)):
            with self.subTest(amount=amount, tax=tax):
                dividend = _activity('dividend', amount, id='div', when='2026-01-01',
                                     withholding_tax={'amount': tax, 'currency': 'BRL'},
                                     metadata={'rikdom_income': {'version': 1, 'amount_basis': 'net'}})
                result = compute_instrument_performance(_portfolio(_activity(), dividend), 'h-fii')
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(result['observed_distributions'], amount)
                self.assertEqual(result['observed_taxes'], tax)
                self.assertEqual(result['profit_amount'], 10 + amount)


if __name__ == '__main__':
    unittest.main()
