"""CLI and offline reports must expose the same calculated financial facts."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from rikdom.performance import compute_performance


START = '2026-01-01T00:00:00Z'
MID = '2026-07-02T00:00:00Z'
END = '2027-01-01T00:00:00Z'


def report_plugin():
    spec = importlib.util.spec_from_file_location('performance_report_plugin', 'plugins/quarto-portfolio-report/plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scenario():
    portfolio = json.loads(Path('tests/fixtures/portfolio.json').read_text())
    portfolio['settings']['base_currency'] = 'BRL'
    portfolio['activities'] = [
        {'id': 'contribution', 'event_type': 'contribution', 'status': 'posted', 'effective_at': MID,
         'money': {'amount': 50, 'currency': 'BRL'}},
        {'id': 'withdrawal', 'event_type': 'withdrawal', 'status': 'posted', 'effective_at': MID,
         'money': {'amount': 10, 'currency': 'BRL'}},
        {'id': 'nonflow', 'event_type': 'dividend', 'status': 'posted', 'effective_at': MID,
         'money': {'amount': 5, 'currency': 'BRL'}},
        {'id': 'pending', 'event_type': 'contribution', 'status': 'pending', 'effective_at': MID,
         'money': {'amount': 999, 'currency': 'BRL'}},
    ]
    snapshots = [{'timestamp': START, 'base_currency': 'BRL', 'totals': {'portfolio_value_base': 100}},
                 {'timestamp': END, 'base_currency': 'BRL', 'totals': {'portfolio_value_base': 165}}]
    return portfolio, snapshots


class PerformanceReportTests(unittest.TestCase):
    def test_selected_return_contract_is_detached_and_preserves_legacy_fields(self):
        from rikdom.performance_report import performance_to_dict
        portfolio, snapshots = scenario()
        result = compute_performance(snapshots, portfolio['activities'], base_currency='BRL')
        output = performance_to_dict(result)
        self.assertEqual(output['net_external_cashflow_base'], 40)
        self.assertEqual(output['twr_method'], 'modified_dietz')
        self.assertEqual(output['mwr_return_basis'], 'annualized_365_day')
        self.assertAlmostEqual(output['twr_return_pct'], 20.823825, places=5)
        output['warnings'].append('changed consumer copy')
        self.assertNotIn('changed consumer copy', result.warnings)

    def test_report_uses_core_returns_and_signed_effective_external_flows(self):
        portfolio, snapshots = scenario()
        before = copy.deepcopy((portfolio, snapshots))
        payload = report_plugin()._build_report_payload(portfolio, snapshots, generated_at=END)
        result = payload['sections']['performance']
        self.assertEqual(result['net_external_cashflow_base'], 40)
        self.assertAlmostEqual(result['twr_return_pct'], 20.823825, places=5)
        rows = payload['sections']['contributions']
        self.assertEqual([(r['activity_id'], r['amount']) for r in rows], [('contribution', 50), ('withdrawal', -10)])
        self.assertEqual(before, (portfolio, snapshots))
        self.assertEqual(result['treatment']['income'], 'Included in portfolio valuations; never added to investment result again')

    def test_report_does_not_treat_invalid_recorded_snapshot_dates_as_valid_bookends(self):
        portfolio, snapshots = scenario()
        snapshots[0]['timestamp'] = '2026-02-29T00:00:00Z'
        payload = report_plugin()._build_report_payload(portfolio, snapshots, generated_at=END)
        output = payload['sections']['performance']
        self.assertEqual(output['twr_method'], 'unavailable')
        self.assertTrue(output['warnings'])
        self.assertIsNone(output['twr_return_pct'])
