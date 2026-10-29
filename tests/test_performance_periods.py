"""Calendar rows reuse the return engine with exact UTC bookends."""
import unittest

from rikdom.performance_periods import compute_calendar_performance


def snapshot(timestamp, value):
    return {'timestamp': timestamp, 'base_currency': 'BRL',
            'totals': {'portfolio_value_base': value}}


def contribution(timestamp, value):
    return {'id': timestamp, 'event_type': 'contribution', 'status': 'posted',
            'effective_at': timestamp, 'money': {'amount': value, 'currency': 'BRL'}}


class CalendarPerformanceTests(unittest.TestCase):
    def compute(self, snapshots, activities=None, **kwargs):
        return compute_calendar_performance(snapshots, activities or [], base_currency='BRL', **kwargs)

    def test_shared_boundary_contribution_belongs_to_ending_month_once(self):
        snaps = [snapshot('2024-01-01T00:00:00Z', 100),
                 snapshot('2024-02-01T00:00:00Z', 160),
                 snapshot('2024-03-01T00:00:00Z', 176)]
        result = self.compute(snaps, [contribution('2024-02-01T00:00:00Z', 50)])
        january, february = result['monthly']
        self.assertEqual([january['label'], february['label']], ['2024-01', '2024-02'])
        self.assertEqual(january['performance']['net_external_cashflow_base'], 50)
        self.assertEqual(february['performance']['net_external_cashflow_base'], 0)
        self.assertAlmostEqual(january['performance']['twr_return_pct'], 10)
        self.assertAlmostEqual(february['performance']['twr_return_pct'], 10)
        self.assertEqual(february['performance']['mwr_return_basis'], 'annualized_365_day')
        self.assertEqual(february['period_end'], '2024-03-01T00:00:00Z')
        self.assertEqual(february['coverage'], 'complete')

    def test_missing_midperiod_boundary_keeps_unavailable_rows(self):
        result = self.compute([snapshot('2024-01-01T00:00:00Z', 100),
                               snapshot('2024-03-01T00:00:00Z', 121)])
        self.assertEqual([r['status'] for r in result['monthly']], ['unavailable', 'unavailable'])
        self.assertIsNone(result['monthly'][0]['performance'])
        self.assertIn('2024-02-01', result['monthly'][0]['warnings'][0])
        self.assertEqual(result['yearly'][0]['coverage'], 'partial')
        self.assertAlmostEqual(result['yearly'][0]['performance']['twr_return_pct'], 21)

    def test_partial_bookends_year_rollover_and_utc_normalization(self):
        result = self.compute([snapshot('2023-12-15T03:00:00+03:00', 100),
                               snapshot('2024-01-01T00:00:00Z', 110),
                               snapshot('2024-01-15T00:00:00Z', 121)])
        self.assertEqual([r['label'] for r in result['yearly']], ['2023', '2024'])
        self.assertEqual([r['coverage'] for r in result['monthly']], ['partial', 'partial'])
        self.assertEqual(result['monthly'][0]['period_start'], '2023-12-15T00:00:00Z')
        self.assertEqual(result['monthly'][1]['period_start'], '2024-01-01T00:00:00Z')

    def test_requested_boundary_cannot_silently_use_nearest_snapshot(self):
        result = self.compute([snapshot('2024-01-15T00:00:00Z', 100),
                               snapshot('2024-02-01T00:00:00Z', 110)], since='2024-01-01')
        self.assertEqual(result['monthly'][0]['coverage'], 'complete')
        self.assertEqual(result['monthly'][0]['status'], 'unavailable')

    def test_no_history_malformed_and_duplicate_snapshots_are_unavailable(self):
        for snaps in ([], [snapshot('invalid', 10)],
                      [snapshot('2024-01-01', 100), snapshot('2024-02-01T00:00:00Z', 110)],
                      [snapshot('2024-01-01T00:00:00Z', 100), snapshot('2024-01-01T00:00:00Z', 101)]):
            with self.subTest(snaps=snaps):
                result = self.compute(snaps)
                self.assertEqual(result['status'], 'unavailable')
                self.assertTrue(result['warnings'])

    def test_unavailable_historical_replay_preserves_evidence_without_fallback(self):
        replay = {'status': 'unavailable', 'snapshots': [], 'valuations': [
            {'as_of': '2024-01-01T00:00:00Z'}, {'as_of': '2024-02-01T00:00:00Z'}],
            'diagnostics': ['stale price']}
        result = self.compute([snapshot('2024-01-01T00:00:00Z', 100),
                               snapshot('2024-02-01T00:00:00Z', 110)], valuation_replay=replay)
        row = result['monthly'][0]
        self.assertEqual(row['status'], 'unavailable')
        self.assertEqual(result['valuation_replay'], replay)
        self.assertIsNone(row['performance'])

    def test_invalid_financial_snapshot_is_not_an_available_row(self):
        result = self.compute([snapshot('2024-01-01T00:00:00Z', None),
                               snapshot('2024-02-01T00:00:00Z', 110)])
        self.assertEqual(result['monthly'][0]['status'], 'unavailable')
        self.assertIsNone(result['monthly'][0]['performance']['twr_return_pct'])

    def test_dated_fx_and_stale_evidence_propagate_per_row(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from rikdom.historical_fx import HistoricalFx
        from rikdom.market_series import load_market_series
        from tests.test_historical_fx import fx_document
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'series.json'
            path.write_text(json.dumps(fx_document()))
            fx = HistoricalFx(load_market_series(path), base_currency='BRL',
                              series_by_currency={'USD': 'usd-brl'}, max_age_seconds=86400)
        snaps = [snapshot('2026-01-01T00:00:00Z', 100), snapshot('2026-02-01T00:00:00Z', 176)]
        flow = contribution('2026-01-06T00:00:00Z', 10)
        flow['money']['currency'] = 'USD'
        row = self.compute(snaps, [flow], historical_fx=fx)['monthly'][0]
        self.assertEqual(row['performance']['net_external_cashflow_base'], 60)
        self.assertIn('synthetic', str(row['performance']['fx_evidence']))
        flow['effective_at'] = '2026-01-08T00:00:00Z'
        stale = self.compute(snaps, [flow], historical_fx=fx)['monthly'][0]
        self.assertEqual(stale['status'], 'unavailable')
        self.assertIsNone(stale['performance']['net_external_cashflow_base'])

    def test_complete_replay_and_benchmark_provenance_are_retained(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from rikdom.benchmarks import make_dir_loader
        snaps = [snapshot('2026-01-01T00:00:00Z', 100), snapshot('2026-02-01T00:00:00Z', 110)]
        replay = {'status': 'complete', 'snapshots': snaps, 'valuations': [], 'diagnostics': []}
        policy = {'benchmarks': [{'id': 'index', 'label': 'Synthetic index', 'kind': 'index', 'currency': 'BRL'}],
                  'strategic_allocation': {'targets': [{'benchmark_id': 'index', 'weight_pct': 100}]}}
        with TemporaryDirectory() as tmp:
            Path(tmp, 'index.jsonl').write_text(''.join(json.dumps({'as_of': s['timestamp'],
                'level': value, 'currency': 'BRL', 'return_convention': 'total_return',
                'source': 'manual:synthetic'}) + '\n' for s, value in zip(snaps, (100, 105))))
            from rikdom.historical_fx import load_historical_fx
            fx = load_historical_fx('data-sample/performance-fx/historical-fx.json', base_currency='BRL')
            row = self.compute([], valuation_replay=replay, policy=policy, historical_fx=fx,
                               benchmark_loader=make_dir_loader(tmp))['monthly'][0]
        self.assertEqual(row['performance']['valuation_status'], 'complete')
        benchmark = row['performance']['benchmarks'][0]
        self.assertAlmostEqual(benchmark['twr_pct'], 5)
        self.assertIn('manual:synthetic', str(benchmark))

    def test_flow_valuation_evidence_at_shared_opening_is_not_counted_again(self):
        snaps = [snapshot('2024-01-01T00:00:00Z', 100),
                 snapshot('2024-02-01T00:00:00Z', 160),
                 snapshot('2024-03-01T00:00:00Z', 176)]
        evidence = {'version': 1, 'scope': 'portfolio', 'base_currency': 'BRL',
                    'rounding_tolerance_base': .01, 'valuations': [{
                        'timestamp': '2024-02-01T00:00:00Z', 'base_currency': 'BRL',
                        'pre_flow_value_base': 110, 'post_flow_value_base': 160,
                        'source': 'Synthetic reviewed boundary'}]}
        rows = self.compute(snaps, [contribution('2024-02-01T00:00:00Z', 50)],
                            flow_valuations=evidence)['monthly']
        self.assertEqual(rows[0]['performance']['twr_method'], 'linked_subperiod')
        self.assertEqual(rows[1]['performance']['twr_method'], 'bookend_ratio')
        self.assertAlmostEqual(rows[1]['performance']['twr_return_pct'], 10)

    def test_correction_outside_month_is_resolved_before_window_selection(self):
        old = contribution('2024-01-15T00:00:00Z', 50)
        old['id'] = 'old'
        corrected = contribution('2024-02-15T00:00:00Z', 50)
        corrected['id'] = 'new'
        corrected['extensions'] = {'rikdom_correction': {
            'version': 1, 'supersedes_activity_id': 'old', 'reason': 'Wrong date'}}
        rows = self.compute([snapshot('2024-01-01T00:00:00Z', 100),
                             snapshot('2024-02-01T00:00:00Z', 110),
                             snapshot('2024-03-01T00:00:00Z', 176)], [old, corrected])['monthly']
        self.assertEqual([r['performance']['net_external_cashflow_base'] for r in rows], [0, 50])

    def test_full_year_is_recomputed_instead_of_adding_months_or_xirrs(self):
        snaps = [snapshot('2024-01-01T00:00:00Z', 100),
                 snapshot('2024-02-01T00:00:00Z', 110),
                 snapshot('2025-01-01T00:00:00Z', 121)]
        year = self.compute(snaps)['yearly'][0]
        self.assertEqual(year['coverage'], 'complete')
        self.assertAlmostEqual(year['performance']['twr_return_pct'], 21)
        self.assertEqual(year['period_end'], '2025-01-01T00:00:00Z')

    def test_bad_timezone_offset_is_rejected(self):
        result = self.compute([snapshot('2024-01-01T00:00:00+03:99', 100),
                               snapshot('2024-02-01T00:00:00Z', 110)])
        self.assertEqual(result['status'], 'unavailable')
