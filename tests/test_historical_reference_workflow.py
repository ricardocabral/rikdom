"""Synthetic full-position evidence through real event, performance and report CLI."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from rikdom.activities import effective_activities
from rikdom.cli import main

SAMPLE = Path('data-sample/historical-workflow')


class HistoricalReferenceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'evidence'
        shutil.copytree(SAMPLE, self.source)
        (self.root / 'unused-fx.jsonl').write_text('')

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                patch.object(socket.socket, 'connect', side_effect=AssertionError('offline only')):
            code = main(list(map(str, arguments)))
        self.assertEqual((code, stderr.getvalue()), (0, ''), stdout.getvalue())
        return json.loads(stdout.getvalue()) if stdout.getvalue().lstrip().startswith('{') else stdout.getvalue()

    def apply_splits(self):
        common = ['market-events', 'apply', '--input', self.source / 'market-events.json',
                  '--event', 'synthetic-fund-split', '--as-of', '2027-01-01T00:00:00Z',
                  '--portfolio', self.source / 'portfolio.json', '--write']
        first = self.invoke(*common, '--review', self.source / 'split-review.json',
                            '--retrieved-before', '2026-08-01T00:00:00Z')
        self.assertTrue(first['write'], first)
        before = json.loads((self.source / 'portfolio.json').read_text())
        revised = self.invoke(*common, '--review', self.source / 'split-revision-review.json')
        self.assertTrue(revised['write'], revised)
        after = json.loads((self.source / 'portfolio.json').read_text())
        self.assertEqual(after['activities'][:len(before['activities'])], before['activities'])
        self.assertEqual(after['holdings'], before['holdings'])
        splits = [row for row in effective_activities(after['activities']) if row['event_type'] == 'split']
        self.assertEqual(len(splits), 1)
        self.assertEqual(splits[0]['corporate_action']['exchange_ratio'], 3)
        unchanged = (self.source / 'portfolio.json').read_bytes()
        repeat = self.invoke(*common, '--review', self.source / 'split-revision-review.json')
        self.assertFalse(repeat['write'])
        self.assertEqual((self.source / 'portfolio.json').read_bytes(), unchanged)

    def common(self):
        return ['--portfolio', self.source / 'portfolio.json', '--snapshots', self.source / 'snapshots.jsonl',
                '--historical-valuations', self.source / 'replay.json',
                '--historical-fx', self.source / 'historical-fx.json',
                '--flow-valuations', self.source / 'flow-valuations.json',
                '--profit-basis', self.source / 'basis.json', '--policy', self.source / 'policy.json',
                '--benchmarks-dir', self.source / 'benchmarks', '--data-dir', self.root / 'data',
                '--fx-history', self.root / 'unused-fx.jsonl']

    def cli_and_report(self):
        calculated = self.invoke('performance', *self.common())
        with patch.dict(os.environ, {'RIKDOM_DISABLE_QUARTO': '1'}):
            self.invoke('viz', *self.common(), '--out', self.root / 'report/dashboard.html')
        report = json.loads((self.root / 'report/quarto-input.json').read_text())
        self.assertEqual(report['sections']['performance'], calculated)
        return calculated

    def test_corrected_split_distribution_transfers_and_flows_share_report_results(self):
        self.apply_splits()
        before = {path: path.read_bytes() for path in self.source.rglob('*') if path.is_file()}
        calculated = self.cli_and_report()
        # 10*10*5 +100 =600. 30*6*6 +140+10 +7*6 =1272.
        self.assertEqual(calculated['valuation_status'], 'complete')
        self.assertEqual(calculated['start_value_base'], 600)
        self.assertEqual(calculated['end_value_base'], 1272)
        self.assertEqual(calculated['net_external_cashflow_base'], 50)
        self.assertEqual(calculated['cashflow_count'], 2)
        self.assertEqual(calculated['internal_transfers']['status'], 'verified')
        self.assertEqual(calculated['internal_transfers']['pairs'][0]['activity_ids'], ['out', 'in'])
        # (650/600)*(1322/750)-1, with withdrawal only changing post-flow NAV.
        self.assertEqual(calculated['twr_method'], 'linked_subperiod')
        self.assertEqual(calculated['twr_return_pct'], 90.955556)
        self.assertNotEqual(calculated['twr_pct'], calculated['twr_return_pct'])
        self.assertAlmostEqual(calculated['mwr_pct'], 96.923381, places=6)
        # Independent investor NPV: -600 -100 at day182 +50+1272 at day365.
        rate = calculated['mwr_pct'] / 100
        self.assertAlmostEqual(-600 - 100 / (1 + rate)**(182/365) + 1322/(1+rate), 0, places=5)
        bridge = calculated['profit_attribution']['bridge']
        self.assertEqual(bridge['status'], 'complete')
        self.assertEqual(bridge['investment_result_base'], 622)
        self.assertEqual(bridge['opening_value_base'] + bridge['net_external_cashflow_base']
                         + bridge['investment_result_base'], bridge['closing_value_base'])
        decomposition = calculated['profit_attribution']['decomposition']
        self.assertEqual(decomposition['status'], 'complete', calculated['profit_attribution']['diagnostics'])
        self.assertEqual(decomposition['net_income_base'], 35)
        self.assertEqual(decomposition['cash_fx_gain_base'], 7)
        self.assertEqual(decomposition['unrealized_price_change_base'], 480)
        self.assertEqual(decomposition['unrealized_fx_change_base'], 100)
        self.assertEqual(decomposition['explained_result_base'], 622)
        self.assertEqual(decomposition['reconciliation_difference_base'], 0)
        benchmark = calculated['benchmarks'][0]
        self.assertEqual(benchmark['twr_pct'], 32)
        self.assertEqual(benchmark['excess_pct'], 58.955556)
        self.assertEqual(benchmark['comparison_status'], 'comparable')
        self.assertEqual(before, {path: path.read_bytes() for path in self.source.rglob('*') if path.is_file()})

    def import_and_review(self):
        shutil.copyfile(self.source / 'seed-portfolio.json', self.source / 'portfolio.json')
        common = ['import-statement', '--plugin', 'normalized-statement-json',
                  '--input', self.source / 'statement.json', '--portfolio', self.source / 'portfolio.json',
                  '--data-dir', self.root / 'data', '--fx-history', self.root / 'unused-fx.jsonl',
                  '--import-log', self.root / 'imports.jsonl', '--write',
                  '--ingested-at', '2027-01-02T00:00:00Z']
        imported = self.invoke(*common, '--review-file', self.source / 'import-review.json',
                               '--import-run-id', 'reference-first')
        self.assertTrue(imported['write'])
        first = json.loads((self.source / 'portfolio.json').read_text())
        self.assertEqual(len(first['activities']), 5)
        self.assertEqual({row['id']: row['account_id'] for row in first['activities']},
                         {'contribute': 'a', 'out': 'a', 'in': 'b', 'distribution': 'a', 'withdraw': 'a'})
        repeated = self.invoke(*common, '--import-run-id', 'reference-second')
        self.assertTrue(repeated['write'])
        second = json.loads((self.source / 'portfolio.json').read_text())
        self.assertEqual(len(second['activities']), 5)
        self.assertEqual(len(second['holdings']), 4)
        self.assertEqual({row['id']: row.get('account_id') for row in second['activities']},
                         {row['id']: row.get('account_id') for row in first['activities']})
    def test_reviewed_recurring_import_reaches_historical_valuation_and_report(self):
        self.import_and_review()
        self.apply_splits()
        calculated = self.cli_and_report()
        self.assertEqual(calculated['twr_return_pct'], 90.955556)
        self.assertEqual(calculated['profit_attribution']['bridge']['investment_result_base'], 622)
        self.assertEqual(calculated['internal_transfers']['status'], 'verified')

    def test_reviewed_recurring_import_to_bundle_restore_replays_without_original_files(self):
        # Requires the sibling analysis-run branch and exercises its real CLI.
        self.import_and_review()
        self.apply_splits()
        calculated = self.cli_and_report()
        run = self.root / 'captured'
        self.invoke('capture-analysis', *self.common(), '--output', run)
        captured = json.loads((run / 'result.json').read_text())
        self.assertEqual(captured, calculated)
        # Replay must be independent of all source files, including nested caches.
        shutil.rmtree(self.source)
        (self.root / 'unused-fx.jsonl').unlink()
        bundle, restored = self.root / 'reference.zip', self.root / 'restored'
        self.invoke('export-analysis', '--run', run, '--output', bundle)
        self.invoke('restore-analysis', '--bundle', bundle, '--output', restored)
        replayed = self.invoke('replay-analysis', '--run', restored)
        self.assertEqual(replayed, calculated)

    def test_unadjusted_prices_are_required_and_no_recorded_total_substitution_occurs(self):
        self.apply_splits()
        path = self.source / 'market-series.json'
        document = json.loads(path.read_text())
        for adjustment in ('split_adjusted', 'total_return_adjusted'):
            document['series'][0]['adjustment'] = adjustment
            path.write_text(json.dumps(document))
            calculated = self.cli_and_report()
            self.assertEqual(calculated['valuation_status'], 'unavailable')
            for field in ('start_value_base', 'end_value_base', 'net_external_cashflow_base',
                          'twr_return_pct', 'mwr_pct'):
                self.assertIsNone(calculated[field])
            self.assertEqual(calculated['profit_attribution']['bridge']['status'], 'unavailable')

    def test_no_full_nav_declaration_keeps_benchmark_excess_unavailable(self):
        self.apply_splits()
        path = self.source / 'replay.json'
        document = json.loads(path.read_text())
        document.pop('return_convention')
        path.write_text(json.dumps(document))
        calculated = self.cli_and_report()
        self.assertEqual(calculated['twr_return_pct'], 90.955556)
        self.assertEqual(calculated['return_convention'], 'unspecified')
        self.assertEqual(calculated['benchmarks'][0]['comparison_status'], 'not_comparable')
        self.assertIsNone(calculated['benchmarks'][0]['excess_pct'])


if __name__ == '__main__':
    unittest.main()
