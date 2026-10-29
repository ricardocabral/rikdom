"""Residual growth uses complete evidence, with no independent income add-back."""
import copy
import json
import math
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom import performance
from rikdom.benchmarks import BenchmarkComparison
from rikdom.historical_fx import HistoricalFx
from rikdom.market_series import load_market_series
from tests.test_historical_fx import FIRST, fx_document

START = '2026-01-01T00:00:00Z'
END = '2027-01-01T00:00:00Z'


def snapshots(start=100, end=150):
    return [{'timestamp': stamp, 'base_currency': 'BRL',
             'totals': {'portfolio_value_base': value}}
            for stamp, value in [(START, start), (END, end)]]


def activity(event='contribution', amount=30, currency='BRL', **changes):
    return {'id': 'synthetic', 'event_type': event, 'effective_at': FIRST,
            'money': {'amount': amount, 'currency': currency}, **changes}


class GrowthBridgeTests(unittest.TestCase):
    def compute(self, acts=(), snaps=None, **changes):
        result = performance.compute_performance(
            snapshots() if snaps is None else snaps, list(acts), base_currency='BRL', **changes)
        self.assertTrue(hasattr(result, 'growth_bridge'), 'PerformanceResult must expose growth_bridge')
        return result.growth_bridge

    def unavailable(self, bridge):
        self.assertEqual(bridge['status'], 'unavailable')
        self.assertIsNone(bridge['investment_result_base'])
        self.assertIsNone(bridge['net_external_cashflow_base'])
        self.assertIsNone(bridge['rounding_adjustment_base'])
        self.assertTrue(bridge['reasons'])
        json.dumps(bridge, allow_nan=False)

    def test_contributions_withdrawals_and_embedded_income_reconcile(self):
        acts = [activity(amount=30), activity('withdrawal', -10, id='withdrawal'),
                activity('dividend', 7, id='dividend'), activity('interest', 4, id='interest'),
                activity('income', 3, id='income'), activity('fee', 2, id='fee'),
                activity('tax_withheld', 1, id='tax')]
        bridge = self.compute(acts)
        self.assertEqual(bridge['status'], 'complete')
        self.assertEqual(bridge['opening_value_base'], 100)
        self.assertEqual(bridge['net_external_cashflow_base'], 20)
        self.assertEqual(bridge['investment_result_base'], 30)
        self.assertEqual(bridge['closing_value_base'], 150)
        self.assertEqual(bridge['rounding_adjustment_base'], 0)
        self.assertEqual(bridge['method'], 'residual_growth')
        self.assertEqual(bridge.get('completeness_scope'), 'arithmetic_reconciliation_of_supplied_inputs')
        self.assertIn('transaction history', bridge['caveat'])
        self.assertIn('snapshot FX', bridge['caveat'])
        self.assertIn('lot gains', bridge['caveat'])
        self.assertEqual(bridge['income_treatment'], 'embedded_in_snapshot_values_not_added_again')
        self.assertEqual(bridge['fees_and_taxes'], 'embedded_in_snapshot_values_not_separately_calculated')
        self.assertEqual(bridge['reasons'], [])

    def test_effective_corrections_and_statuses_not_raw_ledger_determine_growth(self):
        old = activity(amount=99, id='old')
        corrected = activity(amount=25, id='corrected', extensions={'rikdom_correction': {
            'version': 1, 'supersedes_activity_id': 'old', 'reason': 'synthetic correction'}})
        acts = [old, corrected, activity(amount=999, id='cancelled', status='cancelled'),
                activity(amount=999, id='pending', status='pending')]
        before = copy.deepcopy(acts)
        bridge = self.compute(acts)
        self.assertEqual(bridge['net_external_cashflow_base'], 25)
        self.assertEqual(bridge['investment_result_base'], 25)
        self.assertEqual(acts, before)

    def test_selected_window_and_bookends_match_existing_performance(self):
        snaps = snapshots() + [{'timestamp': '2026-07-01T00:00:00Z', 'base_currency': 'BRL',
                               'totals': {'portfolio_value_base': 120}}]
        bridge = self.compute([activity(amount=999)], snaps,
                              since='2026-07-02', until='2027-01-01')
        self.assertEqual((bridge['period_start'], bridge['period_end']),
                         ('2026-07-01T00:00:00Z', END))
        self.assertEqual(bridge['net_external_cashflow_base'], 0)
        self.assertEqual(bridge['investment_result_base'], 30)

    def test_missing_and_malformed_bookends_never_infer_zero(self):
        cases = [[], snapshots()[:1]]
        for totals in [None, {}, {'portfolio_value_base': True},
                       {'portfolio_value_base': math.inf}, {'portfolio_value_base': '100'}]:
            snaps = snapshots()
            snaps[0]['totals'] = totals
            cases.append(snaps)
        for snaps in cases:
            with self.subTest(snaps=snaps):
                self.unavailable(self.compute(snaps=snaps))

    def test_invalid_or_unverified_bookend_currency_blocks_growth(self):
        for currency in [None, 'USD', '', True]:
            snaps = snapshots()
            if currency is None:
                snaps[0].pop('base_currency')
            else:
                snaps[0]['base_currency'] = currency
            with self.subTest(currency=currency):
                self.unavailable(self.compute(snaps=snaps))

    def test_bad_timestamps_and_negative_bookends_block_growth(self):
        for stamp in ['bad', '2026-01-01', '2026-01-01T00:00:00']:
            snaps = snapshots()
            snaps[0]['timestamp'] = stamp
            with self.subTest(stamp=stamp):
                self.unavailable(self.compute(snaps=snaps))
        self.unavailable(self.compute(snaps=snapshots(-1, 100)))

    def test_zero_opening_and_total_loss_can_reconcile_without_a_return(self):
        bridge = self.compute([activity(amount=100)], snapshots(0, 110))
        self.assertEqual(bridge['status'], 'complete')
        self.assertEqual(bridge['investment_result_base'], 10)
        loss = self.compute(snaps=snapshots(100, 0))
        self.assertEqual(loss['investment_result_base'], -100)

    def test_skipped_or_approximated_external_flows_never_make_complete_growth(self):
        for act in [activity(currency='USD'), activity(currency='USD', metadata={'fx_rate_to_base': 5}),
                    activity('transfer_in'), activity('transfer_out'), activity(amount=True),
                    activity(amount=math.inf), activity(effective_at='bad'),
                    activity(effective_at=None), activity(effective_at='2026-01-02'),
                    activity(effective_at='2026-01-02T00:00:00'), activity(currency=''),
                    {**activity(), 'money': None}]:
            with self.subTest(act=act):
                self.unavailable(self.compute([act]))

    def test_ignored_out_of_window_or_cancelled_bad_flow_does_not_block(self):
        acts = [activity(currency='USD', effective_at='2025-01-01T00:00:00Z'),
                activity(currency='USD', status='cancelled', id='cancelled')]
        self.assertEqual(self.compute(acts)['status'], 'complete')

    def test_dated_fx_reconciles_and_missing_or_stale_fx_blocks(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'series.json'
            path.write_text(json.dumps(fx_document()))
            fx = HistoricalFx(load_market_series(path), base_currency='BRL',
                              series_by_currency={'USD': 'usd-brl'}, max_age_seconds=86400)
            bridge = self.compute([activity(amount=10, currency='USD')], historical_fx=fx)
            self.assertEqual(bridge['net_external_cashflow_base'], 50)
            self.assertEqual(bridge['investment_result_base'], 0)
            for act in [activity(currency='EUR'), activity(currency='USD',
                        effective_at='2026-01-04T00:00:00Z')]:
                with self.subTest(act=act):
                    self.unavailable(self.compute([act], historical_fx=fx))

    def test_rounding_is_explicit_and_bridge_reconciles_in_decimal_units(self):
        bridge = self.compute([activity(amount=0.0000004)], snapshots(1.0000004, 2.0000006))
        self.assertEqual(bridge['rounding_decimals'], 6)
        self.assertEqual(bridge['rounding_method'], 'half_even')
        self.assertEqual(bridge['investment_result_base'], 1)
        self.assertEqual(bridge['rounding_adjustment_base'], 0.000001)
        self.assertEqual(sum(Decimal(str(bridge[key])) for key in [
            'opening_value_base', 'net_external_cashflow_base', 'investment_result_base',
            'rounding_adjustment_base']), Decimal(str(bridge['closing_value_base'])))
        json.dumps(bridge, allow_nan=False)

    def test_nonfinite_aggregate_or_residual_is_unavailable(self):
        self.unavailable(self.compute([activity('withdrawal', 1e308)], snapshots(0, 1e308)))
        self.unavailable(self.compute([activity(amount=1e308), activity(amount=1e308, id='two')]))


class PerformanceSerializationTests(unittest.TestCase):
    def serialize(self, result):
        serializer = getattr(performance, 'performance_result_to_dict', None)
        self.assertTrue(callable(serializer), 'performance_result_to_dict must be shared by CLI and reports')
        return serializer(result)

    def result(self, benchmarks=()):
        return performance.PerformanceResult('BRL', START, END, 100, 150, 20, 25, 25, 2,
                                             benchmarks=list(benchmarks))

    def test_legacy_fields_survive_additive_calculation_evidence(self):
        payload = self.serialize(self.result())
        self.assertIn('growth_bridge', payload)
        payload.pop('growth_bridge')
        self.assertEqual(payload.pop('internal_transfers'), {})
        self.assertEqual(payload.pop('return_convention'), 'unspecified')
        self.assertEqual(payload.pop('return_convention_evidence'), [])
        self.assertEqual(payload, {'base_currency': 'BRL', 'period_start': START, 'period_end': END,
            'start_value_base': 100, 'end_value_base': 150, 'net_external_cashflow_base': 20,
            'twr_pct': 25, 'legacy_twr_method': 'modified_dietz', 'twr_return_pct': None,
            'linked_twr_pct': None, 'twr_method': 'unavailable', 'twr_fallback_reason': None,
            'twr_return_basis': 'period', 'mwr_method': 'xirr', 'mwr_return_basis': 'annualized_365_day',
            'mwr_pct': 25, 'cashflow_count': 2, 'warnings': [],
            'fx_status': 'legacy_approximate', 'fx_evidence': []})

    def test_legacy_and_historical_benchmark_conditional_fields_survive(self):
        legacy = BenchmarkComparison('legacy', 'Legacy', 'index', 'BRL', 10, 15, START, END)
        historical = BenchmarkComparison('dated', 'Dated', 'composite', 'BRL', 12, 13, START, END,
            warnings=['Synthetic warning'], components=[legacy], native_currency='USD',
            native_twr_pct=5, return_convention='total_return', fx_evidence=[{'rate': 5}],
            data_provenance=[{'source': 'synthetic'}], comparison_status='comparable')
        legacy_expected = {'benchmark_id': 'legacy', 'label': 'Legacy', 'kind': 'index',
                           'currency': 'BRL', 'twr_pct': 10, 'excess_pct': 15}
        payload = self.serialize(self.result([legacy, historical]))
        self.assertEqual(payload['benchmarks'][0], legacy_expected)
        self.assertEqual(payload['benchmarks'][1], {
            'benchmark_id': 'dated', 'label': 'Dated', 'kind': 'composite', 'currency': 'BRL',
            'twr_pct': 12, 'excess_pct': 13, 'period_start': START, 'period_end': END,
            'native_currency': 'USD', 'native_twr_pct': 5, 'return_convention': 'total_return',
            'comparison_status': 'comparable', 'fx_evidence': [{'rate': 5}],
            'data_provenance': [{'source': 'synthetic'}], 'warnings': ['Synthetic warning'],
            'components': [legacy_expected]})
