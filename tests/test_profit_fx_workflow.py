"""Hand-checkable native/base accounting through CLI and offline artifacts."""
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

from rikdom.cli import main
from rikdom.activities import effective_activities


SAMPLE = Path('data-sample/profit-attribution-fx')


class ProfitFxWorkflowTests(unittest.TestCase):
    def invoke(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
             patch.object(socket.socket, 'connect', side_effect=AssertionError('offline only')):
            code = main(list(map(str, arguments)))
        return code, out.getvalue(), err.getvalue()

    def common(self, source, root):
        return ['--portfolio', source / 'portfolio.json', '--snapshots', source / 'snapshots.jsonl',
                '--historical-fx', source / 'historical-fx.json', '--profit-basis', source / 'basis.json',
                '--fx-history', root / 'unused-fx.jsonl', '--data-dir', root / 'data']

    def cli_and_report(self, source, root):
        common = self.common(source, root)
        code, out, err = self.invoke('performance', *common)
        self.assertEqual((code, err), (0, ''))
        calculated = json.loads(out)
        with patch.dict(os.environ, {'RIKDOM_DISABLE_QUARTO': '1'}):
            code, out, err = self.invoke('viz', *common, '--out', root / 'report/dashboard.html')
        self.assertEqual((code, err), (0, ''))
        report = json.loads((root / 'report/quarto-input.json').read_text())
        self.assertEqual(calculated, report['sections']['performance'])
        return calculated

    def test_sample_cli_and_offline_report_keep_all_multicurrency_components(self):
        source = SAMPLE.resolve()
        before = {path: path.read_bytes() for path in source.iterdir() if path.is_file()}
        with tempfile.TemporaryDirectory() as directory:
            calculated = self.cli_and_report(source, Path(directory))
        expected = json.loads((source / 'expected.json').read_text())
        self.assertEqual(calculated['profit_attribution']['bridge']['investment_result_base'], 550)
        decomposition = calculated['profit_attribution']['decomposition']
        self.assertEqual(decomposition['status'], 'complete', calculated['profit_attribution']['diagnostics'])
        for key, value in expected.items():
            if key != 'investment_result_base':
                self.assertEqual(decomposition[key], value)
        self.assertEqual(before, {path: path.read_bytes() for path in source.iterdir() if path.is_file()})

    def test_missing_acquisition_fx_keeps_bridge_but_not_complete_profit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            shutil.copytree(SAMPLE, source)
            path = source / 'market-series.json'
            data = json.loads(path.read_text())
            for series in data['series']:
                series['observations'] = [row for row in series['observations']
                                          if row['effective_at'] != '2025-12-01T00:00:00Z']
            path.write_text(json.dumps(data))
            calculated = self.cli_and_report(source, root)
        result = calculated['profit_attribution']
        self.assertEqual(result['bridge']['status'], 'complete')
        self.assertEqual(result['decomposition']['status'], 'unavailable')
        self.assertIsNone(result['decomposition']['realized_gain_base'])
        self.assertTrue(result['diagnostics'])

    def test_revised_split_replays_once_into_foreign_fifo_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            shutil.copytree(SAMPLE, source)
            event_source = Path('data-sample/market-events')
            events = json.loads((event_source / 'split-revisions.json').read_text())
            first_review = json.loads((event_source / 'split-review.json').read_text())
            latest_review = json.loads((event_source / 'split-revision-review.json').read_text())
            for review in (first_review, latest_review):
                review.update(holding_id='h', account_id='a')
            for name, value in (('events.json', events), ('first-review.json', first_review),
                                ('latest-review.json', latest_review)):
                (source / name).write_text(json.dumps(value))
            portfolio_path = source / 'portfolio.json'
            portfolio = json.loads(portfolio_path.read_text())
            portfolio['activities'][0]['quantity'] = 12
            portfolio['holdings'][0].update(quantity=18, instrument=events['events'][0]['instrument'])
            portfolio['holdings'][0]['market_value']['amount'] = 108
            portfolio['holdings'][1]['market_value']['amount'] = 160
            portfolio_path.write_text(json.dumps(portfolio))
            basis_path = source / 'basis.json'
            basis = json.loads(basis_path.read_text())
            basis['opening_cash'][0]['amount'] = 100
            basis['closing_cash'][0]['amount'] = 160
            basis['closing_positions'][0].update(quantity=18, market_value_native=108)
            basis_path.write_text(json.dumps(basis))
            snapshot_path = source / 'snapshots.jsonl'
            snapshots = [json.loads(line) for line in snapshot_path.read_text().splitlines()]
            for snapshot, value in zip(snapshots, (1100, 1876)):
                snapshot['totals']['portfolio_value_base'] = value
            snapshot_path.write_text(''.join(json.dumps(row) + '\n' for row in snapshots))
            common = ['market-events', 'apply', '--input', source / 'events.json',
                      '--event', 'synthetic-us-split', '--as-of', '2026-02-01T00:00:00Z',
                      '--portfolio', portfolio_path, '--write']
            code, out, err = self.invoke(*common, '--review', source / 'first-review.json',
                                         '--retrieved-before', '2026-01-02T00:00:00Z')
            self.assertEqual((code, err), (0, ''))
            first = json.loads(portfolio_path.read_text())
            code, out, err = self.invoke(*common, '--review', source / 'latest-review.json')
            self.assertEqual((code, err), (0, ''))
            corrected = json.loads(portfolio_path.read_text())
            self.assertEqual(corrected['activities'][:len(first['activities'])], first['activities'])
            self.assertEqual(corrected['holdings'], first['holdings'])
            splits = [row for row in effective_activities(corrected['activities']) if row['event_type'] == 'split']
            self.assertEqual(len(splits), 1)
            self.assertEqual(splits[0]['corporate_action']['exchange_ratio'], 3)
            before = portfolio_path.read_bytes()
            code, out, err = self.invoke(*common, '--review', source / 'latest-review.json')
            self.assertEqual((code, err), (0, ''))
            self.assertFalse(json.loads(out)['write'])
            self.assertEqual(portfolio_path.read_bytes(), before)
            calculated = self.cli_and_report(source, root)
            result = calculated['profit_attribution']
            self.assertEqual(result['decomposition']['status'], 'complete', result['diagnostics'])
            for key, expected in {'realized_price_gain_base':120, 'realized_fx_gain_base':80,
                                  'unrealized_price_change_base':236, 'unrealized_fx_change_base':80,
                                  'cash_fx_gain_base':260, 'explained_result_base':776,
                                  'reconciliation_difference_base':0}.items():
                self.assertEqual(result['decomposition'][key], expected)
            self.assertEqual(result['bridge']['investment_result_base'], 776)
            self.assertEqual(result['decomposition']['holdings'][0]['closing_quantity'], 18)
            self.assertEqual(result['decomposition']['holdings'][0]['remaining_cost_native'], 60)
            self.assertEqual(result['decomposition']['holdings'][0]['remaining_historical_cost_base'], 240)

            # An economically identical source revision reviewed after the
            # basis cutoff must not masquerade as evidence already known then.
            late = {**events['events'][0]['revisions'][-1],
                    'id': 'synthetic-us-split-r3', 'supersedes': 'synthetic-us-split-r2',
                    'retrieved_at': '2026-01-25T00:00:00Z'}
            events['events'][0]['revisions'].append(late)
            (source / 'events.json').write_text(json.dumps(events))
            late_review = {**latest_review, 'revision_id': late['id'],
                           'reviewed_at': '2026-02-10T00:00:00Z'}
            (source / 'late-review.json').write_text(json.dumps(late_review))
            code, out, err = self.invoke(*common, '--review', source / 'late-review.json',
                                         '--as-of', '2026-02-11T00:00:00Z')
            self.assertEqual((code, err), (0, ''))
            after_cutoff = self.cli_and_report(source, root)['profit_attribution']
            self.assertEqual(after_cutoff['bridge']['status'], 'complete')
            self.assertEqual(after_cutoff['decomposition']['status'], 'unavailable')
            self.assertIsNone(after_cutoff['decomposition']['explained_result_base'])
            self.assertTrue(any('cutoff' in reason for reason in after_cutoff['diagnostics']))
