"""Synthetic captured evidence through the real capture/replay calculations."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout

from rikdom.analysis_runs import capture_performance_run

SCRIPT = Path('scripts/read_portfolio_context.py')
SAMPLE = Path('data-sample/historical-valuation-replay')


class ReadPortfolioContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'canonical'
        shutil.copytree(SAMPLE, self.source)
        (self.source / 'snapshots.jsonl').write_text('')
        (self.source / 'fx.jsonl').write_text('')
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.replay_scratch = self.root / 'os-temp'
        self.replay_scratch.mkdir()
        self.run = self.root / 'saved-run'

    def capture(self, *, flows=True, historical=True, by='portfolio', policy=None):
        inputs = {'portfolio': self.source / 'portfolio.json',
                  'snapshots': self.source / 'snapshots.jsonl',
                  'fx_history': self.source / 'fx.jsonl'}
        if historical:
            inputs.update(historical_valuations=self.source / 'replay.json',
                          historical_fx=self.source / 'historical-fx.json')
        if flows:
            inputs['flow_valuations'] = self.source / 'flow-valuations.json'
        if policy is not None:
            policy_path = self.source / 'policy.json'
            policy_path.write_text(json.dumps(policy))
            inputs['policy'] = policy_path
            if (self.source / 'benchmarks').is_dir():
                inputs['benchmarks_dir'] = self.source / 'benchmarks'
        return capture_performance_run(self.run, inputs=inputs, parameters={'by': by})

    def invoke(self, *args):
        self.assertTrue(SCRIPT.is_file(), 'The external-reader example must exist')
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                patch.object(sys, 'argv', [str(SCRIPT), *map(str, args)]), \
                patch('tempfile.tempdir', str(self.replay_scratch)), \
                patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), \
                patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')):
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            except SystemExit as exc:
                code = exc.code
            else:
                code = 0
        self.assertEqual(list(self.replay_scratch.iterdir()), [], 'Core replay must clean its scratch files')
        return code, out.getvalue(), err.getvalue()

    def read(self):
        return self.invoke('--run', self.run, '--scope', 'portfolio', '--scratch-dir', self.scratch)

    def tree(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob('*') if p.is_file()}

    def test_complete_result_has_exact_evidence_citations_and_no_writes_or_network(self):
        manifest = self.capture()
        before = self.tree(self.source), self.tree(self.run)
        code, out, err = self.read()
        self.assertEqual((code, err), (0, ''))
        context = json.loads(out)
        result = context['result']
        self.assertEqual(context['scope'], 'portfolio')
        # 2*10*5 +20 +3*5 =135; 3*12*6 +20 +3*6 =254; flow=72.
        self.assertEqual(result['valuation_status'], 'complete')
        self.assertEqual(result['start_value_base'], 135)
        self.assertEqual(result['end_value_base'], 254)
        self.assertEqual(result['net_external_cashflow_base'], 72)
        self.assertEqual(result['twr_method'], 'linked_subperiod')
        self.assertEqual(result['twr_return_pct'], 34.814815)
        self.assertEqual(result['base_currency'], 'BRL')
        self.assertEqual(result['period_start'], '2026-01-02T00:00:00Z')
        self.assertEqual(result['period_end'], '2026-01-06T00:00:00Z')
        self.assertEqual(result, json.loads((self.run / 'result.json').read_bytes()))
        evidence = context['capture']
        self.assertEqual(evidence['parameters'], manifest['parameters'])
        self.assertEqual(evidence['methods'], manifest['methods'])
        self.assertEqual(evidence['environment'], manifest['environment'])
        for relative, citation in evidence['files'].items():
            self.assertEqual(citation['path'], str((self.run / relative).resolve()))
            self.assertEqual(citation['sha256'], hashlib.sha256((self.run / relative).read_bytes()).hexdigest())
            self.assertEqual(citation['role'], manifest['files'][relative]['role'])
        self.assertIn('inputs/historical_valuations-series.json', evidence['files'])
        self.assertEqual(evidence['manifest']['sha256'], hashlib.sha256((self.run / 'analysis-run.json').read_bytes()).hexdigest())
        self.assertEqual(before, (self.tree(self.source), self.tree(self.run)))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_dietz_approximation_preserves_raw_method_reason_coverage_and_warnings(self):
        portfolio_path = self.source / 'portfolio.json'
        portfolio = json.loads(portfolio_path.read_text())
        portfolio['settings']['base_currency'] = 'USD'
        portfolio['holdings'] = []
        portfolio['activities'] = [{
            'id': 'synthetic-midpoint-flow', 'event_type': 'contribution', 'status': 'posted',
            'effective_at': '2026-01-06T00:00:00Z', 'money': {'amount': 50, 'currency': 'USD'},
        }]
        portfolio_path.write_text(json.dumps(portfolio))
        (self.source / 'snapshots.jsonl').write_text(''.join(json.dumps({
            'timestamp': when, 'base_currency': 'USD', 'totals': {'portfolio_value_base': value}}) + '\n'
            for when, value in [('2026-01-01T00:00:00Z', 100), ('2026-01-11T00:00:00Z', 165)]))
        self.capture(flows=False, historical=False)
        code, out, err = self.read()
        self.assertEqual((code, err), (0, ''))
        result = json.loads(out)['result']
        self.assertEqual(result['twr_method'], 'modified_dietz')
        # (165 -100 -50) / (100 +50*0.5) =12%; midpoint NAV is unknown.
        self.assertEqual(result['twr_return_pct'], 12)
        self.assertTrue(result['twr_fallback_reason'])
        self.assertTrue(result['warnings'])
        self.assertEqual(result, json.loads((self.run / 'result.json').read_bytes()))

    def test_missing_and_stale_prices_remain_unavailable_even_with_recorded_totals(self):
        for problem in ('missing', 'stale'):
            with self.subTest(problem=problem):
                if self.run.exists():
                    shutil.rmtree(self.run)
                market = json.loads((SAMPLE / 'market.json').read_text())
                if problem == 'missing':
                    market['series'][0]['observations'] = []
                else:
                    market['series'][0]['coverage']['start'] = '2025-12-01T00:00:00Z'
                    for row in market['series'][0]['observations']:
                        row['effective_at'] = row['effective_at'].replace('2026-01', '2025-12')
                        row['retrieved_at'] = row['retrieved_at'].replace('2026-01', '2025-12')
                (self.source / 'market.json').write_text(json.dumps(market))
                (self.source / 'snapshots.jsonl').write_text(''.join(json.dumps({
                    'timestamp': when, 'base_currency': 'BRL',
                    'totals': {'portfolio_value_base': 999999}}) + '\n'
                    for when in ('2026-01-02T00:00:00Z', '2026-01-06T00:00:00Z')))
                self.capture()
                code, out, err = self.read()
                self.assertEqual((code, err), (0, ''))
                result = json.loads(out)['result']
                self.assertEqual(result['valuation_status'], 'unavailable')
                price = result['valuation_replay']['valuations'][0]['positions'][0]['price']
                self.assertEqual(price['status'], 'stale' if problem == 'stale' else 'missing')
                for field in ('start_value_base', 'end_value_base', 'twr_return_pct', 'mwr_pct'):
                    self.assertIsNone(result[field])
                self.assertTrue(result['warnings'])
                self.assertEqual(result, json.loads((self.run / 'result.json').read_bytes()))
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_account_request_cannot_relabel_portfolio_totals(self):
        self.capture()
        code, out, err = self.invoke('--run', self.run, '--scope', 'account', '--scratch-dir', self.scratch)
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertIn('portfolio', err)

    def test_account_capture_cannot_be_presented_as_portfolio_context(self):
        self.capture(flows=False, historical=False, by='account')
        code, out, err = self.read()
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('scope', err.lower())
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_scratch_inside_saved_inputs_is_rejected_without_writes(self):
        self.capture()
        before = self.tree(self.run)
        code, out, err = self.invoke('--run', self.run, '--scope', 'portfolio', '--scratch-dir', self.run / 'inputs')
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('scratch', err.lower())
        self.assertEqual(before, self.tree(self.run))

    def test_tampered_input_result_and_incompatible_environment_fail_cleanly(self):
        self.capture()
        originals = self.tree(self.run)
        for target, data, diagnostic in (
            ('inputs/portfolio.json', b'{}', 'changed'),
            ('result.json', b'{}', 'changed'),
            ('analysis-run.json', json.dumps({**json.loads(originals['analysis-run.json']),
                 'environment': {}}).encode(), 'incompatible'),
        ):
            with self.subTest(target=target):
                (self.run / target).write_bytes(data)
                code, out, err = self.read()
                self.assertEqual(code, 1)
                self.assertEqual(out, '')
                self.assertIn(diagnostic, err)
                self.assertEqual(list(self.scratch.iterdir()), [])
                (self.run / target).write_bytes(originals[target])

    def test_changed_manifest_method_cannot_mislabel_a_reproduced_result(self):
        self.capture()
        path = self.run / 'analysis-run.json'
        manifest = json.loads(path.read_bytes())
        manifest['methods']['twr_method'] = 'invented_exact_method'
        path.write_text(json.dumps(manifest))
        code, out, err = self.read()
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('methods', err)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_malformed_manifest_structures_fail_descriptively_without_tracebacks(self):
        self.capture()
        path = self.run / 'analysis-run.json'
        original = path.read_bytes()
        before = self.tree(self.source)
        for field, value in (
            ('environment', []), ('environment', None), ('environment', 'invalid'),
            ('inputs', ['portfolio', 'snapshots', 'fx_history']), ('inputs', None),
            ('parameters', []), ('parameters', None),
            ('methods', []), ('methods', None),
            ('files', []), ('files', None),
        ):
            with self.subTest(field=field, value=value):
                manifest = json.loads(original)
                manifest[field] = value
                path.write_text(json.dumps(manifest))
                saved = self.tree(self.run)
                code, out, err = self.read()
                self.assertEqual((code, out), (1, ''))
                self.assertIn('Context read failed:', err)
                self.assertIn(field, err)
                self.assertNotIn('Traceback', err)
                self.assertEqual(list(self.scratch.iterdir()), [])
                self.assertEqual(saved, self.tree(self.run))
        self.assertEqual(before, self.tree(self.source))

    def test_malformed_consumed_values_and_required_citations_fail_cleanly(self):
        self.capture()
        path = self.run / 'analysis-run.json'
        original = path.read_bytes()
        missing = object()
        cases = [
            (('created_at',), value, 'created_at')
            for value in (missing, None, [], '')
        ] + [
            (('inputs', 'portfolio'), value, 'inputs.portfolio')
            for value in (None, [], {}, '')
        ] + [
            (('parameters', field), value, 'parameters.' + field)
            for field, value in (('since', []), ('until', {}), ('analysis_as_of', 3),
                                 ('instrument', []), ('terminal_value', {}))
        ] + [
            (('files', 'result.json'), value, 'result.json')
            for value in ([], None)
        ] + [
            (('files', 'result.json', field), value, field)
            for field, values in (
                ('role', (missing, None, [], '')),
                ('bytes', (missing, None, True, -1, 1.0)),
                ('sha256', (missing, None, [], 'invalid')),
                ('original_sha256', (None, 'invalid')),
            ) for value in values
        ]
        for keys, value, diagnostic in cases:
            with self.subTest(keys=keys, value=value):
                manifest = json.loads(original)
                target = manifest
                for key in keys[:-1]:
                    target = target[key]
                if value is missing:
                    del target[keys[-1]]
                else:
                    target[keys[-1]] = value
                path.write_text(json.dumps(manifest))
                saved = self.tree(self.run)
                code, out, err = self.read()
                self.assertEqual((code, out), (1, ''))
                self.assertIn('Context read failed:', err)
                self.assertIn(diagnostic, err)
                self.assertNotIn('Traceback', err)
                self.assertEqual(list(self.scratch.iterdir()), [])
                self.assertEqual(saved, self.tree(self.run))

    def test_missing_captured_input_fails_without_falling_back_to_originals(self):
        self.capture()
        (self.run / 'inputs/portfolio.json').unlink()
        code, out, err = self.read()
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('portfolio.json', err)
        self.assertTrue((self.source / 'portfolio.json').is_file())
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_mutation_after_snapshot_cannot_change_result_or_cited_hashes(self):
        self.capture()
        manifest_bytes = (self.run / 'analysis-run.json').read_bytes()
        from rikdom.cli import cmd_performance

        def change_saved_run_then_calculate(args):
            (self.run / 'inputs/portfolio.json').write_text('{}')
            (self.run / 'analysis-run.json').write_text('{}')
            return cmd_performance(args)

        with patch('rikdom.cli.cmd_performance', side_effect=change_saved_run_then_calculate):
            code, out, err = self.read()
        self.assertEqual((code, err), (0, ''))
        context = json.loads(out)
        self.assertEqual(context['result']['start_value_base'], 135)
        self.assertEqual(context['capture']['manifest']['sha256'], hashlib.sha256(manifest_bytes).hexdigest())
        self.assertEqual(context['capture']['files']['inputs/portfolio.json']['sha256'],
                         json.loads(manifest_bytes)['files']['inputs/portfolio.json']['sha256'])
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_self_consistent_changed_result_still_requires_real_calculation_match(self):
        self.capture()
        self.replace_payload('result.json', b'{"twr_return_pct": 999}\n')
        code, out, err = self.read()
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('differs', err)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def replace_payload(self, relative, data):
        (self.run / relative).write_bytes(data)
        path = self.run / 'analysis-run.json'
        manifest = json.loads(path.read_bytes())
        digest = hashlib.sha256(data).hexdigest()
        manifest['files'][relative].update(bytes=len(data), sha256=digest)
        if relative == 'result.json':
            manifest['output_sha256'] = digest
        path.write_text(json.dumps(manifest))

    def test_malformed_but_rehashed_evidence_is_rejected(self):
        self.capture()
        originals = self.tree(self.run)
        for relative, data in (
            ('inputs/portfolio.json', b'{"settings": {}, "settings": {}}'),
            ('inputs/portfolio.json', b'{"invalid": NaN}'),
            ('inputs/portfolio.json', b'{"invalid": 1e999}'),
            ('inputs/snapshots.jsonl', b'{"timestamp": "torn"}'),
            ('result.json', b'{"twr_pct": 1, "twr_pct": 2}'),
        ):
            with self.subTest(relative=relative, data=data):
                self.replace_payload(relative, data)
                code, out, err = self.read()
                self.assertEqual(code, 1)
                self.assertEqual(out, '')
                self.assertIn('Invalid', err)
                self.assertEqual(list(self.scratch.iterdir()), [])
                for name, original in originals.items():
                    (self.run / name).write_bytes(original)

    def test_malformed_rehashed_policy_shapes_fail_cleanly_without_writes(self):
        self.capture(policy={})
        before = self.tree(self.source)
        cases = [
            ({'strategic_allocation': [{}]}, 'strategic_allocation'),
            ({'strategic_allocation': {'targets': [None]}}, 'strategic_allocation.targets[0]'),
        ] + [
            ({'strategic_allocation': {'targets': value}}, 'strategic_allocation.targets')
            for value in (None, {}, 'invalid', 3)
        ] + [
            ({'strategic_allocation': {'targets': [value]}}, 'strategic_allocation.targets[0]')
            for value in ([], 'invalid', 3)
        ] + [
            ({'strategic_allocation': {'targets': [{'benchmark_id': []}]}}, 'benchmark_id'),
        ] + [
            ({'benchmarks': value}, 'benchmarks')
            for value in (None, {}, 'invalid', 3)
        ] + [
            ({'benchmarks': [value]}, 'benchmarks[0]')
            for value in (None, [], 'invalid', 3)
        ] + [
            ({'benchmarks': [{'id': value}]}, 'benchmarks[0].id')
            for value in (None, [], {}, 3)
        ] + [
            ({'benchmarks': [{}]}, 'benchmarks[0].id'),
        ] + [
            ({'benchmarks': [{'id': 'blend', 'kind': 'composite', 'components': value}]},
             'benchmarks[0].components')
            for value in (None, {}, 'invalid', 3)
        ] + [
            ({'benchmarks': [{'id': 'blend', 'kind': 'composite', 'components': [value]}]},
             'benchmarks[0].components[0]')
            for value in (None, [], 'invalid', 3)
        ] + [
            ({'benchmarks': [{'id': 'blend', 'kind': 'composite',
                              'components': [{'benchmark_id': value}]}]}, 'benchmark_id')
            for value in (None, [], {}, 3)
        ]
        for policy, diagnostic in cases:
            with self.subTest(policy=policy):
                self.replace_payload('inputs/policy.json', json.dumps(policy).encode())
                saved = self.tree(self.run)
                code, out, err = self.read()
                self.assertEqual((code, out), (1, ''))
                self.assertIn('Context read failed:', err)
                self.assertIn('policy', err)
                self.assertIn(diagnostic, err)
                self.assertNotIn('Traceback', err)
                self.assertEqual(list(self.scratch.iterdir()), [])
                self.assertEqual(saved, self.tree(self.run))
        self.assertEqual(before, self.tree(self.source))

    def test_policy_input_cannot_be_replaced_with_a_jsonl_record_list(self):
        self.capture(policy={})
        path = self.run / 'analysis-run.json'
        manifest = json.loads(path.read_bytes())
        manifest['inputs']['policy'] = manifest['inputs']['snapshots']
        path.write_text(json.dumps(manifest))
        before = self.tree(self.source), self.tree(self.run)
        code, out, err = self.read()
        self.assertEqual((code, out), (1, ''))
        self.assertIn('policy', err)
        self.assertIn('object', err)
        self.assertNotIn('Traceback', err)
        self.assertEqual(before, (self.tree(self.source), self.tree(self.run)))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_partial_calculation_policy_with_composite_benchmark_replays_unchanged(self):
        benchmarks = self.source / 'benchmarks'
        benchmarks.mkdir()
        (benchmarks / 'index.jsonl').write_text(''.join(json.dumps({
            'as_of': when, 'level': level, 'currency': 'BRL',
            'return_convention': 'total_return', 'source': 'manual:synthetic',
        }) + '\n' for when, level in [
            ('2026-01-02T00:00:00Z', 100), ('2026-01-06T00:00:00Z', 110)]))
        # Capture accepts calculation-only policies without full IPS schema fields.
        manifest = self.capture(policy={
            'benchmarks': [
                {'id': 'index', 'kind': 'index', 'currency': 'BRL'},
                {'id': 'blend', 'kind': 'composite', 'currency': 'BRL',
                 'components': [{'benchmark_id': 'index', 'weight_pct': 100}]},
            ],
            'strategic_allocation': {'targets': [{'benchmark_id': 'blend', 'weight_pct': 100}]},
        })
        before = self.tree(self.source), self.tree(self.run)
        code, out, err = self.read()
        self.assertEqual((code, err), (0, ''))
        context = json.loads(out)
        self.assertEqual(context['result'], json.loads((self.run / 'result.json').read_bytes()))
        self.assertEqual(context['result']['benchmarks'][0]['benchmark_id'], 'blend')
        self.assertEqual(context['result']['benchmarks'][0]['twr_pct'], 10)
        self.assertEqual(context['capture']['inputs']['policy'], manifest['inputs']['policy'])
        self.assertIn('inputs/benchmarks/index.jsonl', context['capture']['files'])
        self.assertEqual(before, (self.tree(self.source), self.tree(self.run)))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_unsupported_format_and_unsafe_inventory_are_rejected(self):
        self.capture()
        path = self.run / 'analysis-run.json'
        original = path.read_text()
        for change, diagnostic in (
            ({'format_version': '99'}, 'Unsupported'),
            ({'files': {'../canonical/portfolio.json': {}}}, 'Unsafe'),
            ({'replayable': False}, 'omitted'),
        ):
            with self.subTest(change=change):
                path.write_text(json.dumps({**json.loads(original), **change}))
                code, out, err = self.read()
                self.assertEqual(code, 1)
                self.assertEqual(out, '')
                self.assertIn(diagnostic, err)
                self.assertEqual(list(self.scratch.iterdir()), [])
        path.write_text(original)


if __name__ == '__main__':
    unittest.main()
