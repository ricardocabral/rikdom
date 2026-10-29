"""Offline CLI acceptance for dated cashflow and benchmark FX evidence."""
import contextlib
from datetime import datetime
import copy
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rikdom.cli import main

START = '2026-01-01T00:00:00Z'
MID = '2026-07-02T00:00:00Z'
END = '2027-01-01T00:00:00Z'


class HistoricalFxCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.portfolio = self.root / 'portfolio.json'
        self.snaps = self.root / 'snapshots.jsonl'
        self.config = self.root / 'historical-fx.json'
        self.series = self.root / 'series.json'
        self.policy = self.root / 'policy.json'
        fixture = Path(__file__).parent / 'fixtures' / 'portfolio.json'
        self.payload = json.loads(fixture.read_text())
        self.payload['settings']['base_currency'] = 'BRL'
        self.payload['accounts'] = [{'id': 'synthetic-account', 'label': 'Synthetic account'}]
        self.payload['activities'] = [{'id': 'synthetic-usd-contribution', 'event_type': 'contribution',
            'status': 'posted', 'account_id': self.payload['accounts'][0]['id'], 'effective_at': MID,
            'money': {'amount': 10, 'currency': 'USD'}, 'metadata': {'fx_rate_to_base': 999}}]
        self.portfolio.write_text(json.dumps(self.payload))
        self.snapshots = [{'timestamp': START, 'base_currency': 'BRL',
                          'totals': {'portfolio_value_base': 100}},
                         {'timestamp': END, 'base_currency': 'BRL',
                          'totals': {'portfolio_value_base': 176}}]
        for snapshot in self.snapshots:
            snapshot['metadata'] = {'rikdom_return_convention': {
                'version': 1, 'kind': 'total_return', 'source': 'manual:synthetic-full-NAV'}}
        self.write_snaps()
        self.series_payload = {'contract_version': '1.0', 'series': [{
            'id': 'usd-brl', 'kind': 'fx', 'currency': 'BRL',
            'currency_pair': {'base': 'USD', 'quote': 'BRL'}, 'adjustment': 'not_applicable',
            'coverage': {'start': START, 'end': END},
            'license': {'name': 'CC0-1.0', 'uri': 'https://creativecommons.org/publicdomain/zero/1.0/'},
            'observations': [{'id': key, 'effective_at': stamp, 'retrieved_at': stamp,
                'source': 'manual:synthetic-test', 'value': value, 'currency': 'BRL', 'supersedes': None}
                for key, stamp, value in [('start', START, 5), ('mid', MID, 5), ('end', END, 6)]]}]}
        self.series.write_text(json.dumps(self.series_payload))
        self.config_payload = {'contract_version': '1.0', 'market_series_file': 'series.json',
            'series_by_currency': {'USD': 'usd-brl'}, 'max_age_seconds': 0, 'retrieved_before': None}
        self.config.write_text(json.dumps(self.config_payload))
        self.policy.write_text(json.dumps({'benchmarks': [{'id': 'foreign', 'label': 'Synthetic index',
            'kind': 'index', 'currency': 'USD'}], 'strategic_allocation': {
                'targets': [{'benchmark_id': 'foreign', 'weight_pct': 100}]}}))
        (self.root / 'foreign.jsonl').write_text('\n'.join(json.dumps({
            'as_of': stamp, 'level': level, 'currency': 'USD', 'return_convention': 'total_return',
            'source': 'manual:synthetic-total-return-index'}) for stamp, level in [(START, 100), (END, 110)]) + '\n')

    def write_snaps(self):
        self.snaps.write_text('\n'.join(map(json.dumps, self.snapshots)) + '\n')

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                patch.object(socket.socket, 'connect', side_effect=AssertionError('network disabled')):
            try:
                rc = main(['performance', '--portfolio', str(self.portfolio), '--snapshots', str(self.snaps),
                    '--historical-fx', str(self.config), *map(str, args)])
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def test_real_cashflow_and_foreign_benchmark_replay_offline_without_writes(self):
        before = {p: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result = self.run_cli('--policy', self.policy, '--benchmarks-dir', self.root)
        self.assertEqual((result[0], result[2]), (0, ''))
        output = json.loads(result[1])
        self.assertEqual(output['net_external_cashflow_base'], 50)
        self.assertEqual(output['fx_status'], 'complete')
        self.assertTrue(output['fx_evidence'])
        self.assertIsNotNone(output['mwr_pct'])
        bench = output['benchmarks'][0]
        self.assertEqual(bench['currency'], 'BRL')
        self.assertEqual(bench['twr_pct'], 32)
        self.assertTrue(bench['fx_evidence'])
        self.assertEqual(datetime.fromisoformat(bench['period_start'].replace('Z', '+00:00')),
                         datetime.fromisoformat(START.replace('Z', '+00:00')))
        self.assertEqual(datetime.fromisoformat(bench['period_end'].replace('Z', '+00:00')),
                         datetime.fromisoformat(END.replace('Z', '+00:00')))
        self.assertEqual(bench['return_convention'], 'total_return')
        self.assertTrue(bench['data_provenance'])
        self.assertAlmostEqual(bench['excess_pct'], output['twr_return_pct'] - 32, places=6)
        self.assertEqual(result, self.run_cli('--policy', self.policy, '--benchmarks-dir', self.root))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_missing_portfolio_convention_preserves_returns_without_claiming_excess(self):
        for snapshot in self.snapshots:
            snapshot.pop('metadata', None)
        self.write_snaps()
        code, out, err = self.run_cli('--policy', self.policy, '--benchmarks-dir', self.root)
        self.assertEqual((code, err), (0, ''))
        output = json.loads(out)
        self.assertIsNotNone(output['twr_return_pct'])
        self.assertEqual(output['benchmarks'][0]['twr_pct'], 32)
        self.assertEqual(output['benchmarks'][0]['comparison_status'], 'not_comparable')
        self.assertIsNone(output['benchmarks'][0]['excess_pct'])

    def test_tracked_sample_replays_linked_twr(self):
        sample = Path(__file__).resolve().parents[1] / 'data-sample' / 'performance-fx'
        rc, out, err = self.run_cli('--portfolio', sample / 'portfolio.json',
            '--snapshots', sample / 'snapshots.jsonl', '--historical-fx', sample / 'historical-fx.json',
            '--flow-valuations', sample / 'flow-valuations.json')
        self.assertEqual((rc, err), (0, ''))
        output = json.loads(out)
        self.assertEqual(output['twr_return_pct'], 21)
        self.assertEqual(output['net_external_cashflow_base'], 50)

    def test_dated_flow_supports_linked_twr(self):
        evidence = self.root / 'flow-valuations.json'
        evidence.write_text(json.dumps({'version': 1, 'scope': 'portfolio', 'base_currency': 'BRL',
            'rounding_tolerance_base': 0.01, 'valuations': [{'timestamp': MID, 'base_currency': 'BRL',
                'pre_flow_value_base': 110, 'post_flow_value_base': 160, 'source': 'synthetic boundary'}]}))
        rc, out, err = self.run_cli('--flow-valuations', evidence)
        self.assertEqual((rc, err), (0, ''))
        output = json.loads(out)
        self.assertEqual(output['twr_method'], 'linked_subperiod')
        self.assertEqual(output['twr_return_pct'], 21)

    def test_missing_and_stale_fx_never_use_current_or_metadata_rate(self):
        for kind in ['missing', 'stale']:
            with self.subTest(kind=kind):
                payload = copy.deepcopy(self.series_payload)
                payload['series'][0]['observations'] = payload['series'][0]['observations'][:1] if kind == 'stale' else []
                self.series.write_text(json.dumps(payload))
                rc, out, err = self.run_cli('--policy', self.policy, '--benchmarks-dir', self.root)
                self.assertEqual((rc, err), (0, ''))
                output = json.loads(out)
                self.assertEqual(output['fx_status'], 'unavailable')
                for field in ['twr_pct', 'mwr_pct', 'twr_return_pct', 'net_external_cashflow_base']:
                    self.assertIsNone(output[field])
                self.assertTrue(output['warnings'])
                self.assertIsNone(output['benchmarks'][0]['twr_pct'])
                self.assertIsNone(output['benchmarks'][0]['excess_pct'])

    def test_scoped_rows_keep_dated_evidence(self):
        account = self.payload['accounts'][0]['id']
        for snap in self.snapshots:
            snap['totals']['by_account'] = {account: snap['totals']['portfolio_value_base']}
        self.write_snaps()
        rc, out, err = self.run_cli('--by', 'account')
        self.assertEqual((rc, err), (0, ''))
        row = json.loads(out)['by_account'][0]
        self.assertEqual(row['net_external_cashflow_base'], 50)
        self.assertEqual(row['fx_status'], 'complete')
        self.assertTrue(row['fx_evidence'])

    def test_invalid_config_and_instrument_mode_fail_without_json(self):
        for args, config in [(['--by', 'instrument'], self.config_payload),
                ([], {**self.config_payload, 'unknown': True}),
                ([], {**self.config_payload, 'max_age_seconds': True}),
                ([], {**self.config_payload, 'retrieved_before': '2026-01-01'}),
                ([], {**self.config_payload, 'contract_version': '2.0'})]:
            self.config.write_text(json.dumps(config))
            rc, out, err = self.run_cli(*args)
            self.assertEqual((rc, out), (1, ''))
            self.assertIn('--historical-fx', err)
        self.config.write_text('{"contract_version":"1.0","contract_version":"1.0"}')
        rc, out, err = self.run_cli()
        self.assertEqual((rc, out), (1, ''))
        self.assertIn('--historical-fx', err)

    def test_non_increasing_window_preserves_unavailable_json_with_policy(self):
        referenced_policy = json.loads(self.policy.read_text())
        for policy in ({}, referenced_policy):
            with self.subTest(policy=policy):
                self.snapshots = self.snapshots[:1]
                self.write_snaps()
                self.policy.write_text(json.dumps(policy))
                rc, out, err = self.run_cli('--policy', self.policy, '--benchmarks-dir', self.root)
                self.assertEqual((rc, err), (0, ''))
                output = json.loads(out)
                self.assertEqual(output['twr_method'], 'unavailable')
                self.assertIsNone(output['twr_return_pct'])
                self.assertIsNone(output['mwr_pct'])
                self.assertTrue(any('window' in warning.lower() for warning in output['warnings']))
                self.assertTrue(any('benchmark' in warning.lower() and 'unavailable' in warning.lower()
                                    for warning in output['warnings']))
                self.assertEqual(output.get('benchmarks', []), [])

    def test_invalid_benchmark_currency_keeps_portfolio_and_other_comparisons(self):
        policy = json.loads(self.policy.read_text())
        del policy['benchmarks'][0]['currency']
        policy['benchmarks'].append({'id': 'native', 'label': 'Synthetic native index', 'kind': 'index'})
        policy['strategic_allocation']['targets'].append({'benchmark_id': 'native', 'weight_pct': 0})
        self.policy.write_text(json.dumps(policy))
        for name, currency in [('foreign', 'US$'), ('native', 'BRL')]:
            (self.root / f'{name}.jsonl').write_text('\n'.join(json.dumps({
                'as_of': stamp, 'level': level, 'currency': currency,
                'return_convention': 'total_return', 'source': 'manual:synthetic-index'})
                for stamp, level in [(START, 100), (END, 110)]) + '\n')
        rc, out, err = self.run_cli('--policy', self.policy, '--benchmarks-dir', self.root)
        self.assertEqual((rc, err), (0, ''))
        output = json.loads(out)
        self.assertEqual(output['net_external_cashflow_base'], 50)
        self.assertIsNotNone(output['twr_return_pct'])
        comparisons = {row['benchmark_id']: row for row in output['benchmarks']}
        bad = comparisons['foreign']
        self.assertEqual(bad['comparison_status'], 'unavailable')
        self.assertIsNone(bad['twr_pct'])
        self.assertIsNone(bad['excess_pct'])
        self.assertTrue(any('currency' in warning.lower() for warning in bad['warnings']))
        good = comparisons['native']
        self.assertEqual(good['comparison_status'], 'comparable')
        self.assertEqual(good['twr_pct'], 10)
        self.assertAlmostEqual(good['excess_pct'], output['twr_return_pct'] - 10, places=6)
