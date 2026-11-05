"""Real CLI/offline report parity with explicit local performance evidence."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from rikdom.cli import main


class PerformanceDataCliTests(unittest.TestCase):
    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                patch.object(socket.socket, 'connect', side_effect=AssertionError('offline only')):
            try:
                rc = main(args)
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def test_cli_and_offline_report_share_linked_return_and_result_bridge(self):
        sample = Path('data-sample/performance-fx').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = ['--portfolio', str(sample / 'portfolio.json'), '--snapshots', str(sample / 'snapshots.jsonl'),
                      '--historical-fx', str(sample / 'historical-fx.json'),
                      '--flow-valuations', str(sample / 'flow-valuations.json'), '--data-dir', str(root / 'data')]
            (root / 'policy.json').write_text(json.dumps({
                'benchmarks':[{'id':'foreign','label':'Synthetic index','kind':'index','currency':'USD'}],
                'strategic_allocation':{'targets':[{'benchmark_id':'foreign','weight_pct':100}]}}))
            (root / 'foreign.jsonl').write_text(''.join(json.dumps({
                'as_of':stamp,'level':level,'currency':'USD','return_convention':'total_return',
                'source':'manual:synthetic-index'}) + '\n' for stamp,level in (
                    ('2026-01-01T00:00:00Z',100),('2027-01-01T00:00:00Z',110))))
            common.extend(['--policy',str(root / 'policy.json'),'--benchmarks-dir',str(root)])
            before = {p: p.read_bytes() for p in sample.iterdir() if p.is_file()}
            rc, stdout, stderr = self.invoke(['performance', *common])
            self.assertEqual((rc, stderr), (0, ''))
            cli = json.loads(stdout)
            self.assertEqual(cli['twr_return_pct'], 21)
            calendar = cli['calendar_performance']
            self.assertEqual(len(calendar['monthly']), 12)
            self.assertEqual(calendar['yearly'][0]['coverage'], 'complete')
            self.assertEqual(calendar['yearly'][0]['performance']['twr_return_pct'], 21)
            self.assertEqual(cli['benchmarks'][0]['twr_pct'],32)
            self.assertEqual(cli['benchmarks'][0]['comparison_status'],'comparable')
            self.assertEqual(cli['profit_attribution']['bridge']['investment_result_base'], 26)
            with patch.dict(os.environ, {'RIKDOM_DISABLE_QUARTO': '1'}):
                rc, stdout, stderr = self.invoke(['viz', *common, '--out', str(root / 'report/dashboard.html')])
            self.assertEqual((rc, stderr), (0, ''))
            report = json.loads((root / 'report/quarto-input.json').read_text())
            self.assertEqual(report['sections']['performance'], cli)
            self.assertEqual(before, {p: p.read_bytes() for p in sample.iterdir() if p.is_file()})

    def test_calendar_months_match_offline_report_and_preserve_scope_contract(self):
        from tests.test_performance_periods import snapshot, contribution
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = json.loads(Path('tests/fixtures/portfolio.json').read_text())
            portfolio['settings']['base_currency'] = 'BRL'
            portfolio['activities'] = [contribution('2024-02-01T00:00:00Z', 50)]
            snapshots = [snapshot('2024-01-01T00:00:00Z', 100),
                         snapshot('2024-02-01T00:00:00Z', 160),
                         snapshot('2024-03-01T00:00:00Z', 176)]
            (root / 'portfolio.json').write_text(json.dumps(portfolio))
            (root / 'snapshots.jsonl').write_text(''.join(json.dumps(s) + '\n' for s in snapshots))
            common = ['--portfolio', str(root / 'portfolio.json'), '--snapshots', str(root / 'snapshots.jsonl'),
                      '--data-dir', str(root / 'data')]
            rc, stdout, stderr = self.invoke(['performance', *common])
            self.assertEqual((rc, stderr), (0, ''))
            cli = json.loads(stdout)['calendar_performance']
            self.assertEqual([r['performance']['net_external_cashflow_base'] for r in cli['monthly']], [50, 0])
            for row in cli['monthly']:
                self.assertAlmostEqual(row['performance']['twr_return_pct'], 10)
            with patch.dict(os.environ, {'RIKDOM_DISABLE_QUARTO': '1'}):
                rc, stdout, stderr = self.invoke(['viz', *common, '--out', str(root / 'report/dashboard.html')])
            self.assertEqual((rc, stderr), (0, ''))
            report = json.loads((root / 'report/quarto-input.json').read_text())
            self.assertEqual(report['sections']['performance']['calendar_performance'], cli)
            for scope in ('account', 'strategic_bucket'):
                rc, stdout, stderr = self.invoke(['performance', *common, '--by', scope])
                self.assertEqual((rc, stderr), (0, ''))
                self.assertEqual(json.loads(stdout)['calendar_performance']['status'], 'unavailable_for_scope')

    def test_new_sidecars_are_rejected_for_instrument_scope(self):
        rc, stdout, stderr = self.invoke(['performance', '--by', 'instrument', '--historical-valuations', 'missing.json'])
        self.assertEqual(rc, 1)
        self.assertEqual(stdout, '')
        self.assertIn('portfolio', stderr)

    def test_enrichment_cli_reads_local_request_without_bootstrapping_portfolio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / 'request.json'
            request.write_text(json.dumps({'contract_version': '1.0',
                'source': {'path': str(Path('data-sample/market-series.json').resolve())},
                'lookups': [{'series_id': 'example-price', 'as_of': '2026-01-03T16:00:00Z', 'max_age_seconds': 86400}]}))
            rc, stdout, stderr = self.invoke(['enrichment', '--plugin', 'local-market-series', '--request', str(request)])
            self.assertEqual((rc, stderr), (0, ''))
            output = json.loads(stdout)
            self.assertEqual(output['lookups'][0]['observation']['value'], 101)
            self.assertEqual(output['lookups'][0]['status'], 'available')

    def test_enrichment_sdk_loads_and_replays_through_real_runtime(self):
        from rikdom.plugin_engine.pipeline import run_enrichment_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rc, stdout, stderr = self.invoke(['plugin', 'init', 'synthetic-provider', '--type', 'enrichment', '--dest', str(root)])
            self.assertEqual(rc, 0, stderr)
            result = run_enrichment_pipeline('synthetic-provider', str(root), {
                'contract_version': '1.0', 'source': {'path': str(Path('data-sample/market-series.json').resolve())},
                'lookups': [{'series_id': 'example-price', 'as_of': '2026-01-03T16:00:00Z', 'max_age_seconds': 86400}]})
            self.assertEqual(result['lookups'][0]['observation']['value'], 101)

    def test_explicit_historical_positions_replace_recorded_values_and_missing_inputs_block_fallback(self):
        sample = Path('data-sample/historical-valuation-replay').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = json.loads(Path('tests/fixtures/portfolio.json').read_text())
            portfolio['settings']['base_currency'] = 'BRL'
            portfolio['activities'] = []
            (root / 'portfolio.json').write_text(json.dumps(portfolio))
            (root / 'snapshots.jsonl').write_text(json.dumps({'timestamp':'2026-01-01T00:00:00Z',
                'base_currency':'BRL','totals':{'portfolio_value_base':999999}}) + '\n')
            replay = json.loads((sample / 'replay.json').read_text())
            replay['market_series_file'] = str(sample / 'market.json')
            (root / 'replay.json').write_text(json.dumps(replay))
            args = ['performance', '--portfolio', str(root / 'portfolio.json'), '--snapshots', str(root / 'snapshots.jsonl'),
                    '--historical-valuations', str(root / 'replay.json'), '--data-dir', str(root / 'data')]
            rc, stdout, stderr = self.invoke(args)
            self.assertEqual((rc, stderr), (0, ''))
            output = json.loads(stdout)
            self.assertEqual(output['start_value_base'], 135)
            self.assertEqual(output['end_value_base'], 254)
            self.assertEqual(output['valuation_status'], 'complete')
            self.assertEqual(output['valuation_replay']['valuations'][0]['status'], 'complete')
            replay['retrieved_before'] = '2025-01-01T00:00:00Z'
            (root / 'replay.json').write_text(json.dumps(replay))
            before = {p:p.read_bytes() for p in root.iterdir() if p.is_file()}
            rc, stdout, stderr = self.invoke(args)
            self.assertEqual((rc, stderr), (0, ''))
            output = json.loads(stdout)
            self.assertEqual(output['valuation_status'], 'unavailable')
            for field in ('start_value_base','end_value_base','net_external_cashflow_base','twr_return_pct','mwr_pct'):
                self.assertIsNone(output[field])
            self.assertIsNone(output['profit_attribution']['bridge']['investment_result_base'])
            self.assertEqual(before, {p:p.read_bytes() for p in root.iterdir() if p.is_file()})

    def test_reviewed_basis_exposes_hand_checked_fifo_profit_in_cli(self):
        sample = Path('data-sample/profit-attribution').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            rc, stdout, stderr = self.invoke(['performance', '--portfolio', str(sample / 'portfolio.json'),
                '--snapshots', str(sample / 'snapshots.jsonl'), '--profit-basis', str(sample / 'basis.json'),
                '--data-dir', str(Path(tmp) / 'data')])
            self.assertEqual((rc, stderr), (0, ''))
            output = json.loads(stdout)['profit_attribution']
            self.assertEqual(output['bridge']['investment_result_base'], 80)
            self.assertEqual(output['decomposition']['status'], 'complete')
            self.assertEqual(output['decomposition']['realized_gain_base'], 76)
            self.assertEqual(output['decomposition']['unrealized_change_base'], -2)
            self.assertEqual(output['decomposition']['net_income_base'], 10)

    def test_enriched_cache_replays_the_same_financial_values_offline(self):
        sample = Path('data-sample/historical-valuation-replay').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / 'request.json'
            request.write_text(json.dumps({'contract_version':'1.0','source':{'path':str(sample / 'market.json')},'lookups':[]}))
            rc, stdout, stderr = self.invoke(['enrichment','--plugin','local-market-series','--request',str(request)])
            self.assertEqual((rc, stderr), (0, ''))
            (root / 'cache.json').write_text(json.dumps(json.loads(stdout)['market_series']))
            replay = json.loads((sample / 'replay.json').read_text())
            replay['market_series_file'] = 'cache.json'
            (root / 'replay.json').write_text(json.dumps(replay))
            portfolio = json.loads(Path('tests/fixtures/portfolio.json').read_text())
            portfolio['settings']['base_currency'] = 'BRL'
            portfolio['activities'] = []
            (root / 'portfolio.json').write_text(json.dumps(portfolio))
            args = ['performance','--portfolio',str(root / 'portfolio.json'),
                    '--historical-valuations',str(root / 'replay.json'),'--data-dir',str(root / 'data')]
            first = self.invoke(args)
            self.assertEqual((first[0],first[2]),(0,''))
            output = json.loads(first[1])
            self.assertEqual((output['start_value_base'],output['end_value_base']),(135,254))
            self.assertEqual(first,self.invoke(args))
            with patch.dict(os.environ, {'RIKDOM_DISABLE_QUARTO':'1'}):
                rc, stdout, stderr = self.invoke(['viz',*args[1:],'--out',str(root / 'report/dashboard.html')])
            self.assertEqual((rc,stderr),(0,''))
            report = json.loads((root / 'report/quarto-input.json').read_text())
            self.assertEqual(report['sections']['performance'], output)

    def test_tracked_position_replay_has_coherent_foreign_funding_and_linked_boundary(self):
        sample = Path('data-sample/historical-valuation-replay').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            rc, stdout, stderr = self.invoke(['performance','--portfolio',str(sample / 'portfolio.json'),
                '--historical-valuations',str(sample / 'replay.json'),
                '--historical-fx',str(sample / 'historical-fx.json'),
                '--flow-valuations',str(sample / 'flow-valuations.json'),'--data-dir',str(Path(tmp) / 'data')])
        self.assertEqual((rc,stderr),(0,''))
        output = json.loads(stdout)
        self.assertEqual((output['start_value_base'],output['end_value_base']),(135,254))
        self.assertEqual(output['net_external_cashflow_base'],72)
        self.assertEqual(output['profit_attribution']['bridge']['investment_result_base'],47)
        self.assertEqual(output['twr_method'],'linked_subperiod')
        self.assertEqual(output['twr_return_pct'],34.814815)
