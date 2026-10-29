"""Historical cashflows use dated rates and propagate incomplete data per scope."""
import json
import math
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.historical_fx import HistoricalFx
from rikdom.market_series import load_market_series
from rikdom.performance import (
    compute_performance, compute_performance_by_account,
    compute_performance_by_strategic_bucket, extract_external_cashflows,
)
from tests.test_historical_fx import FIRST, SECOND, fx_document

START = '2026-01-01T00:00:00Z'
END = '2027-01-01T00:00:00Z'


def flow(aid='one', when=FIRST, currency='USD', amount=10, **changes):
    return {'id': aid, 'event_type': 'contribution', 'account_id': 'a',
            'holding_id': 'h', 'effective_at': when,
            'money': {'amount': amount, 'currency': currency}, **changes}


def snapshots(end=210):
    return [{'timestamp': START, 'base_currency': 'BRL', 'totals': {
                'portfolio_value_base': 100, 'by_account': {'a': 100, 'b': 100},
                'by_strategic_bucket': {'asset_class:equity': 100, 'asset_class:bond': 100}}},
            {'timestamp': END, 'base_currency': 'BRL', 'totals': {
                'portfolio_value_base': end, 'by_account': {'a': end, 'b': 110},
                'by_strategic_bucket': {'asset_class:equity': end, 'asset_class:bond': 110}}}]


def boundaries(first=(100, 150), second=(150, 210)):
    return {'version': 1, 'scope': 'portfolio', 'base_currency': 'BRL',
            'rounding_tolerance_base': 0.0001, 'valuations': [
                {'timestamp': when, 'base_currency': 'BRL', 'pre_flow_value_base': pre,
                 'post_flow_value_base': post, 'source': 'synthetic independent valuation'}
                for when, (pre, post) in [(FIRST, first), (SECOND, second)]]}


class PerformanceHistoricalFxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'fx.json'
        path.write_text(json.dumps(fx_document()))
        self.series = load_market_series(path)
        self.fx = self.resolver()

    def resolver(self, **changes):
        return HistoricalFx(self.series, **{'base_currency': 'BRL',
            'series_by_currency': {'USD': 'usd-brl'}, 'max_age_seconds': 86400, **changes})

    def compute(self, acts=None, **changes):
        return compute_performance(snapshots(), [flow(), flow('two', SECOND)] if acts is None else acts,
                                   base_currency='BRL', historical_fx=self.fx, **changes)

    def test_two_dates_support_hand_checked_linked_return_and_xirr(self):
        result = self.compute(flow_valuations=boundaries())
        self.assertEqual(result.net_external_cashflow_base, 110)
        self.assertEqual(result.twr_method, 'linked_subperiod')
        self.assertEqual(result.twr_return_pct, 0)
        self.assertAlmostEqual(result.mwr_pct, 0, places=6)
        self.assertEqual(result.fx_status, 'complete')
        self.assertEqual([row['amount_base'] for row in result.fx_evidence], [50, 60])
        self.assertEqual([row['activity_id'] for row in result.fx_evidence], ['one', 'two'])

    def test_nonzero_linking_and_xirr_satisfy_investor_cashflows(self):
        result = compute_performance(snapshots(259.6), [flow(), flow('two', SECOND)],
            base_currency='BRL', historical_fx=self.fx,
            flow_valuations=boundaries((110, 160), (176, 236)))
        self.assertEqual(result.twr_return_pct, 33.1)
        rate = result.mwr_pct / 100
        origin = datetime.fromisoformat(START.replace('Z', '+00:00'))
        npv = -100 + 259.6 / (1 + rate)
        for when, amount in [(FIRST, 50), (SECOND, 60)]:
            years = (datetime.fromisoformat(when.replace('Z', '+00:00')) - origin).total_seconds() / (365 * 86400)
            npv -= amount / (1 + rate) ** years
        self.assertAlmostEqual(npv, 0, places=5)

    def test_missing_stale_unknown_wrong_pair_block_all_portfolio_returns_no_fallback(self):
        for fx, act in [
            (self.resolver(series_by_currency={}), flow()),
            (self.fx, flow(when='2026-01-04T00:00:00Z')),
            (self.resolver(series_by_currency={'USD': 'unknown'}), flow()),
            (self.resolver(series_by_currency={'EUR': 'usd-brl'}), flow(currency='EUR')),
        ]:
            with self.subTest(act=act, fx=fx):
                act['metadata'] = {'fx_rate_to_base': 999}
                result = compute_performance(snapshots(), [act], base_currency='BRL', historical_fx=fx,
                                             fx_rates_to_base={'USD': 999, 'EUR': 999})
                self.assertEqual(result.fx_status, 'unavailable')
                self.assertIsNone(result.net_external_cashflow_base)
                self.assertIsNone(result.twr_pct)
                self.assertIsNone(result.twr_return_pct)
                self.assertIsNone(result.mwr_pct)
                self.assertIsNone(result.fx_evidence[0]['amount_base'])

    def test_native_identity_and_signed_withdrawal(self):
        result = self.compute([flow(currency='BRL', amount=-10, event_type='withdrawal')])
        self.assertEqual(result.net_external_cashflow_base, -10)
        self.assertEqual(result.fx_evidence[0]['native_amount'], -10)
        self.assertEqual(result.fx_evidence[0]['amount_base'], -10)
        self.assertEqual(result.fx_status, 'complete')

    def test_account_and_bucket_only_invalidate_affected_scope(self):
        acts = [flow(currency='EUR')]
        accounts, _ = compute_performance_by_account(snapshots(), acts,
            base_currency='BRL', historical_fx=self.fx)
        portfolio = {'asset_type_catalog': [{'id': 'stock', 'asset_class': 'equity'}],
                     'holdings': [{'id': 'h', 'asset_type_id': 'stock'}]}
        policy = {'strategic_allocation': {'targets': [
            {'dimension': 'asset_class', 'bucket': 'equity'}]}}
        buckets, _ = compute_performance_by_strategic_bucket(snapshots(), acts,
            base_currency='BRL', historical_fx=self.fx, portfolio=portfolio, policy=policy)
        for rows in (accounts, buckets):
            bad, good = (rows[0], rows[1]) if rows is accounts else (rows[1], rows[0])
            self.assertEqual(bad.fx_status, 'unavailable')
            self.assertIsNone(bad.twr_pct)
            self.assertIsNone(bad.mwr_pct)
            self.assertIsNone(bad.net_external_cashflow_base)
            self.assertEqual(len(bad.fx_evidence), 1)
            self.assertEqual(good.fx_status, 'complete')
            self.assertEqual(good.twr_pct, 10)

    def test_corrections_cancellations_and_window_filter_evidence(self):
        original = flow('old', currency='EUR')
        corrected = flow('new', SECOND, extensions={'rikdom_correction': {
            'version': 1, 'supersedes_activity_id': 'old', 'reason': 'synthetic correction'}})
        result = self.compute([original, corrected, flow('cancelled', currency='EUR', status='cancelled'),
                               flow('outside', when='2025-12-01T00:00:00Z', currency='EUR')])
        self.assertEqual(result.net_external_cashflow_base, 60)
        self.assertEqual(result.fx_status, 'complete')
        self.assertEqual([row['activity_id'] for row in result.fx_evidence], ['new'])

    def test_invalid_data_and_overflow_do_not_yield_complete_returns(self):
        for act in [flow(amount=math.inf), flow(amount=True), flow(amount=1e308),
                    flow(currency='bad'), flow(effective_at='bad'),
                    flow(effective_at='2026-01-02T00:00:00')]:
            with self.subTest(act=act):
                result = self.compute([act])
                self.assertEqual(result.fx_status, 'unavailable')
                self.assertIsNone(result.twr_return_pct)
                self.assertIsNone(result.net_external_cashflow_base)

    def test_direct_extraction_uses_same_dates_and_discloses_missing(self):
        flows, warnings = extract_external_cashflows([flow(), flow('missing', currency='EUR')],
            'BRL', historical_fx=self.fx)
        self.assertEqual([cf.amount_base for cf in flows], [50])
        self.assertTrue(any('unavailable' in warning.lower() for warning in warnings))

    def test_legacy_remains_disclosed_and_transfer_identity_unresolved(self):
        result = compute_performance(snapshots(), [flow()], base_currency='BRL',
                                     fx_rates_to_base={'USD': 5})
        self.assertEqual(result.fx_status, 'legacy_approximate')
        self.assertEqual(result.net_external_cashflow_base, 50)
        historical = self.compute([flow(event_type='transfer_in')])
        self.assertTrue(any('Transfer identity unresolved' in w for w in historical.warnings))
        self.assertEqual(historical.twr_method, 'modified_dietz')

    def test_reporting_currency_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            compute_performance(snapshots(), [], base_currency='USD', historical_fx=self.fx)

    def test_finite_aggregate_overflow_blocks_returns(self):
        acts = [flow(str(i), currency='BRL', amount=1e308) for i in range(2)]
        result = self.compute(acts)
        self.assertIsNone(result.net_external_cashflow_base)
        self.assertIsNone(result.twr_return_pct)
        self.assertIsNone(result.mwr_pct)
        self.assertEqual(result.fx_status, 'unavailable')

    def test_invalid_diagnostics_remain_strict_json_serializable(self):
        from dataclasses import asdict
        for act in [flow(amount=math.inf), flow(currency=math.inf),
                    flow(effective_at=math.inf)]:
            with self.subTest(act=act):
                result = self.compute([act])
                self.assertIsNone(result.twr_return_pct)
                json.dumps(asdict(result), allow_nan=False)

    def test_scoped_complete_conversions_use_both_dated_rates(self):
        rows, warnings = compute_performance_by_account(snapshots(), [flow(), flow('two', SECOND)],
            base_currency='BRL', historical_fx=self.fx)
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0].net_external_cashflow_base, 110)
        self.assertEqual(rows[0].twr_pct, 0)
        self.assertEqual(rows[0].mwr_pct, 0)
        self.assertEqual([row['rate'] for row in rows[0].fx_evidence], [5, 6])

    def test_stale_lookup_status_is_retained_in_unavailable_conversion(self):
        result = self.compute([flow(when='2026-01-04T00:00:00Z')])
        row = result.fx_evidence[0]
        self.assertEqual(row['lookup_status'], 'stale')
        self.assertEqual(row['status'], 'unavailable')
        self.assertEqual(row['observation']['id'], 'first')
        self.assertEqual(row['reason'], 'maximum_age_exceeded')
