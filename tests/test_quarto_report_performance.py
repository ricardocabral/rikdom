"""Report performance consumes the CLI calculation contract without browser math."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rikdom.performance import compute_performance
from rikdom.plugin_engine.pipeline import run_output_pipeline

spec = importlib.util.spec_from_file_location('performance_report_plugin', Path('plugins/quarto-portfolio-report/plugin.py'))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


def example():
    return ({'settings': {'base_currency': 'USD'}, 'activities': [
        {'id': 'deposit', 'status': 'posted', 'event_type': 'contribution',
         'effective_at': '2026-01-06T00:00:00Z', 'money': {'amount': 50, 'currency': 'USD'}},
        {'id': 'income', 'status': 'posted', 'event_type': 'dividend',
         'effective_at': '2026-01-08T00:00:00Z', 'money': {'amount': 5, 'currency': 'USD'}},
    ]}, [
        {'timestamp': '2026-01-01T00:00:00Z', 'base_currency': 'USD', 'totals': {'portfolio_value_base': 100}},
        {'timestamp': '2026-01-11T00:00:00Z', 'base_currency': 'USD', 'totals': {'portfolio_value_base': 176}},
    ])


class ReportPerformanceTests(unittest.TestCase):
    def test_payload_reuses_cli_contract_and_does_not_mutate_inputs(self):
        portfolio, snapshots = example()
        before = copy.deepcopy((portfolio, snapshots))
        sections = plugin._build_report_payload(portfolio, snapshots)['sections']
        self.assertIn('performance', sections)
        from rikdom.performance import performance_result_to_dict
        expected = performance_result_to_dict(compute_performance(
            snapshots, portfolio['activities'], base_currency='USD'))
        self.assertEqual({key:sections['performance'][key] for key in expected}, expected)
        self.assertEqual(sections['performance']['net_external_cashflow_base'], 50)
        self.assertEqual(sections['performance']['growth_bridge']['investment_result_base'], 26)
        self.assertEqual((portfolio, snapshots), before)

    def test_scoped_performance_is_unavailable(self):
        portfolio, snapshots = example()
        portfolio['holdings'] = [{'id': 'h', 'account_id': 'a', 'asset_type_id': 'stock',
                                  'market_value': {'amount': 176, 'currency': 'USD'}}]
        payload = plugin._build_report_payload(portfolio, snapshots)
        for view in payload['report_views']:
            self.assertIsNone(view['sections'].get('performance'))
            self.assertEqual(view['sections'].get('performance_context', {}).get('status'), 'unavailable_for_scope')

    def test_invalid_snapshot_preserves_other_sections_and_discloses_unavailability(self):
        portfolio, snapshots = example()
        snapshots.append({'timestamp': '2026-02-29T00:00:00Z', 'totals': {'portfolio_value_base': 999}})
        sections = plugin._build_report_payload(portfolio, snapshots)['sections']
        self.assertIsNone(sections.get('performance'))
        self.assertEqual(sections.get('performance_context', {}).get('status'), 'unavailable')
        self.assertTrue(sections.get('performance_context', {}).get('warnings'))
        self.assertEqual(len(sections['timeline']), 2)

    def test_explicit_local_flow_evidence_matches_cli_offline_and_keeps_sources(self):
        portfolio, snapshots = example()
        evidence = {'version': 1, 'scope': 'portfolio', 'base_currency': 'USD', 'rounding_tolerance_base': .01,
                    'valuations': [{'timestamp': '2026-01-06T00:00:00Z', 'base_currency': 'USD',
                                    'pre_flow_value_base': 110, 'post_flow_value_base': 160,
                                    'source': 'Synthetic custodian before/after <source>'}]}
        portfolio['extensions'] = {'rikdom_report': {'performance': {'flow_valuations_path': 'flows.json'}}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'RIKDOM_DISABLE_QUARTO': '1'}):
            root = Path(tmp)
            (root / 'portfolio.json').write_text(json.dumps(portfolio))
            (root / 'snapshots.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in snapshots))
            (root / 'flows.json').write_text(json.dumps(evidence))
            with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
                run_output_pipeline(plugin_name='quarto-portfolio-report', plugins_dir='plugins',
                                    portfolio_path=str(root / 'portfolio.json'), snapshots_path=str(root / 'snapshots.jsonl'),
                                    output_dir=str(root / 'output'))
                cli = subprocess.run([__import__('sys').executable, '-m', 'rikdom', 'performance',
                                      '--portfolio', str(root / 'portfolio.json'), '--snapshots', str(root / 'snapshots.jsonl'),
                                      '--flow-valuations', str(root / 'flows.json'), '--fx-history', str(root / 'missing.jsonl')],
                                     text=True, capture_output=True, check=True)
            payload = json.loads((root / 'output/quarto-input.json').read_text())
            self.assertEqual(payload['sections']['performance'], json.loads(cli.stdout))
            self.assertEqual(payload['sections']['performance']['twr_return_pct'], 21)
            self.assertEqual(payload['sections']['performance']['twr_method'], 'linked_subperiod')
            self.assertIn('Synthetic custodian', json.dumps(payload['sections']['performance_context']))
            self.assertNotIn(str(root), json.dumps(payload['sections']['performance_context']))

    def test_invalid_local_preferences_do_not_silently_fall_back(self):
        portfolio, snapshots = example()
        portfolio['extensions'] = {'rikdom_report': {'performance': {'flow_valuations_path': 'https://example.test/flows.json'}}}
        sections = plugin._build_report_payload(portfolio, snapshots)['sections']
        self.assertIsNone(sections.get('performance'))
        self.assertEqual(sections.get('performance_context', {}).get('status'), 'unavailable')
        self.assertTrue(sections['performance_context']['warnings'])

    @unittest.skipUnless(os.environ.get('RIKDOM_PLAYWRIGHT_MODULE') and shutil.which('node'), 'Opt-in Playwright runtime check')
    def test_runtime_displays_python_metrics_and_suppresses_unsupported_filters(self):
        portfolio, snapshots = example()
        portfolio['holdings'] = [{'id': 'h', 'account_id': 'a', 'market_value': {'amount': 176, 'currency': 'USD'}}]
        payload = plugin._build_report_payload(portfolio, snapshots)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'payload.json'
            path.write_text(json.dumps(payload))
            result = subprocess.run([shutil.which('node'), 'tests/browser/report_performance.cjs', str(path)],
                                    text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_historical_fx_and_benchmark_preferences_reuse_core_evidence(self):
        from rikdom.benchmarks import make_dir_loader
        from rikdom.historical_fx import load_historical_fx
        from rikdom.performance import performance_result_to_dict
        from tests.test_historical_fx import fx_document
        portfolio, snapshots = example()
        portfolio['settings']['base_currency'] = 'BRL'
        for snapshot in snapshots:
            snapshot['base_currency'] = 'BRL'
            snapshot['metadata'] = {'rikdom_return_convention': {
                'version': 1, 'kind': 'total_return', 'source': 'manual:synthetic-full-NAV'}}
        policy = {'benchmarks': [{'id': 'test-index', 'label': 'Synthetic reference', 'kind': 'index', 'currency': 'BRL'}],
                  'strategic_allocation': {'targets': [{'dimension': 'asset_class', 'bucket': 'stocks', 'weight_pct': 100, 'benchmark_id': 'test-index'}]}}
        config = {'contract_version': '1.0', 'market_series_file': 'series.json',
                  'series_by_currency': {'USD': 'usd-brl'}, 'max_age_seconds': 86400, 'retrieved_before': None}
        options = {'historical_fx_path': 'fx.json', 'policy_path': 'policy.json', 'benchmarks_dir': 'benchmarks'}
        portfolio['extensions'] = {'rikdom_report': {'performance': options}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'series.json').write_text(json.dumps(fx_document()))
            (root / 'fx.json').write_text(json.dumps(config))
            (root / 'policy.json').write_text(json.dumps(policy))
            (root / 'benchmarks').mkdir()
            (root / 'benchmarks/test-index.jsonl').write_text(''.join(json.dumps({
                'as_of': row['timestamp'], 'level': level, 'currency': 'BRL',
                'return_convention': 'total_return', 'source': 'Synthetic benchmark source',
            }) + '\n' for row, level in zip(snapshots, [100, 110])))
            with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
                sections = plugin._build_report_payload(portfolio, snapshots, source_dir=root)['sections']
                expected = performance_result_to_dict(compute_performance(
                    snapshots, portfolio['activities'], base_currency='BRL',
                    historical_fx=load_historical_fx(root / 'fx.json', base_currency='BRL'),
                    policy=policy, benchmark_loader=make_dir_loader(root / 'benchmarks')))
            self.assertEqual({key:sections['performance'][key] for key in expected}, expected)
            self.assertEqual(sections['performance']['net_external_cashflow_base'], 300)
            self.assertEqual(sections['performance']['benchmarks'][0]['twr_pct'], 10)
            self.assertEqual(sections['performance']['benchmarks'][0]['comparison_status'], 'comparable')
            self.assertIn('Synthetic benchmark source', json.dumps(sections['performance']['benchmarks']))
            self.assertIn('synthetic', json.dumps(sections['performance']['fx_evidence']))
            # Historical mode never falls back to today's/undated report FX.
            config['max_age_seconds'] = 0
            portfolio['activities'][0]['effective_at'] = '2026-01-07T00:00:00Z'
            (root / 'fx.json').write_text(json.dumps(config))
            stale = plugin._build_report_payload(portfolio, snapshots, source_dir=root)['sections']['performance']
            self.assertIsNone(stale['twr_return_pct'])
            self.assertEqual(stale['growth_bridge']['status'], 'unavailable')

    def test_malformed_selected_policy_and_null_paths_are_unavailable(self):
        portfolio, snapshots = example()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'policy.json').write_text('[]')
            for options in ({'policy_path': 'policy.json'}, {'flow_valuations_path': None}):
                with self.subTest(options=options):
                    portfolio['extensions'] = {'rikdom_report': {'performance': options}}
                    sections = plugin._build_report_payload(portfolio, snapshots, source_dir=root)['sections']
                    self.assertIsNone(sections.get('performance'))
                    self.assertEqual(sections['performance_context']['status'], 'unavailable')

    def test_selected_null_documents_reject_instead_of_using_absent_input_defaults(self):
        portfolio, snapshots = example()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'null.json').write_text('null')
            for option, reason in (('flow_valuations_path', 'flow-valuations'), ('policy_path', 'policy JSON object')):
                with self.subTest(option=option):
                    portfolio['extensions'] = {'rikdom_report': {'performance': {option: 'null.json'}}}
                    sections = plugin._build_report_payload(portfolio, snapshots, source_dir=root)['sections']
                    self.assertIsNone(sections['performance'])
                    self.assertEqual(sections['performance_context']['status'], 'unavailable')
                    self.assertIn(reason, ' '.join(sections['performance_context']['warnings']))
