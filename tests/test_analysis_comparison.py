"""Compare real core captures, using synthetic portfolio evidence only."""
from __future__ import annotations

import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.analysis_runs import capture_performance_run
from rikdom.cli import main


class AnalysisComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.portfolio = json.loads(Path('tests/fixtures/portfolio.json').read_text())
        self.portfolio['schema_version'] = '2.0.0'
        self.portfolio['settings']['base_currency'] = 'USD'
        self.portfolio['holdings'] = []
        self.portfolio['activities'] = []
        self.snapshots = [{
            'timestamp': date, 'base_currency': 'USD',
            'totals': {'portfolio_value_base': value},
            'metadata': {'rikdom_return_convention': {
                'version': 1, 'kind': 'total_return', 'source': 'synthetic statement'}},
        } for date, value in [('2026-01-01T00:00:00Z', 100), ('2026-12-31T00:00:00Z', 110)]]
        self.fx = []
        self.extra_inputs = {}

    def capture(self, name, **parameters):
        inputs = {}
        for role, value in [('portfolio', self.portfolio), ('snapshots', self.snapshots), ('fx_history', self.fx)]:
            path = self.root / (role + ('.json' if role == 'portfolio' else '.jsonl'))
            path.write_text(json.dumps(value) if role == 'portfolio' else ''.join(json.dumps(row) + '\n' for row in value))
            inputs[role] = path
        inputs.update(self.extra_inputs)
        run = self.root / name
        capture_performance_run(run, inputs=inputs,
                                parameters={'analysis_as_of': '2027-01-01T00:00:00Z', **parameters})
        return run

    def compare(self, before, after):
        from rikdom.analysis_comparison import compare_analysis_runs
        return compare_analysis_runs(before, after)

    def inventory(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_unchanged_evidence_has_zero_recorded_result_delta_and_no_writes(self):
        before, after = self.capture('before'), self.capture('after')
        inventory = self.inventory()
        result = self.compare(before, after)
        self.assertEqual(result['format'], 'rikdom-analysis-comparison')
        self.assertEqual(result['format_version'], '1.0')
        self.assertFalse(result['replayed'])
        self.assertTrue(result['compatibility']['comparable'])
        self.assertEqual(result['explanation']['classification'], 'unchanged')
        self.assertEqual(result['deltas']['end_value_base']['delta'], 0)
        self.assertEqual(result['before']['result']['sha256'], hashlib.sha256((before / 'result.json').read_bytes()).hexdigest())
        self.assertEqual(self.inventory(), inventory)

    def add_flow(self, amount=10, identifier='flow'):
        event = {'id': identifier, 'event_type': 'contribution', 'status': 'posted',
                 'effective_at': '2026-06-01T00:00:00Z', 'account_id': 'synthetic',
                 'money': {'amount': amount, 'currency': 'USD'},
                 'source_ref': 'synthetic-statement', 'idempotency_key': identifier}
        self.portfolio['activities'].append(event)
        return event

    def test_controlled_source_correction_exposes_links_and_fixed_evidence(self):
        self.add_flow()
        before = self.capture('before')
        corrected = self.add_flow(5, 'corrected')
        corrected['extensions'] = {'rikdom_correction': {
            'version': 1, 'supersedes_activity_id': 'flow', 'reason': 'Reviewed source correction'}}
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'controlled_source_correction')
        self.assertEqual(result['explanation']['causation'], 'not_established_by_recorded_comparison')
        self.assertEqual(result['changes']['activities']['added'][0]['id'], 'corrected')
        self.assertEqual(result['changes']['activities']['added'][0]['correction']['supersedes_activity_id'], 'flow')
        self.assertEqual(result['changes']['input_roles'], ['portfolio'])
        self.assertEqual(result['deltas']['net_external_cashflow_base']['delta'], -5)
        self.assertTrue(result['explanation']['held_fixed']['parameters'])
        self.assertTrue(result['explanation']['held_fixed']['other_input_bytes'])

    def test_multiple_drivers_remain_unresolved(self):
        self.add_flow()
        before = self.capture('before')
        corrected = self.add_flow(5, 'corrected')
        corrected['extensions'] = {'rikdom_correction': {
            'version': 1, 'supersedes_activity_id': 'flow', 'reason': 'Reviewed source correction'}}
        self.snapshots[-1]['totals']['portfolio_value_base'] = 120
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'unresolved')
        self.assertEqual(result['changes']['input_roles'], ['portfolio', 'snapshots'])
        self.assertEqual(len(result['changes']['valuations']), 1)
        self.assertEqual(result['deltas']['end_value_base']['delta'], 10)

    def historical_fx(self, *, stale=False):
        self.portfolio['settings']['base_currency'] = 'BRL'
        for snapshot in self.snapshots:
            snapshot['base_currency'] = 'BRL'
        flow = self.add_flow()
        flow['effective_at'] = '2026-06-01T00:00:00Z'
        self.series = {'contract_version': '1.0', 'series': [{
            'id': 'usd-brl', 'kind': 'fx', 'currency': 'BRL',
            'currency_pair': {'base': 'USD', 'quote': 'BRL'},
            'adjustment': 'not_applicable',
            'coverage': {'start': '2026-01-01T00:00:00Z', 'end': '2027-01-01T00:00:00Z'},
            'license': {'name': 'CC0', 'uri': 'https://example.invalid/license'},
            'observations': [{'id': 'original', 'effective_at': flow['effective_at'],
                              'retrieved_at': flow['effective_at'], 'source': 'synthetic',
                              'value': 5, 'currency': 'BRL', 'supersedes': None}]}]}
        series_path = self.root / 'series.json'
        series_path.write_text(json.dumps(self.series))
        config = self.root / 'historical-fx.json'
        config.write_text(json.dumps({
            'contract_version': '1.0', 'market_series_file': 'series.json',
            'series_by_currency': {} if stale else {'USD': 'usd-brl'},
            'max_age_seconds': 86400, 'retrieved_before': None}))
        self.extra_inputs['historical_fx'] = config
        return series_path

    def test_controlled_fx_revision_retains_vintage_pointers_and_observed_delta(self):
        series_path = self.historical_fx()
        before = self.capture('before')
        observations = self.series['series'][0]['observations']
        observations.append({**observations[0], 'id': 'revised', 'value': 5.5,
                             'retrieved_at': '2026-06-02T00:00:00Z', 'supersedes': 'original'})
        series_path.write_text(json.dumps(self.series))
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'controlled_fx_revision')
        self.assertEqual(result['deltas']['net_external_cashflow_base']['delta'], 5)
        self.assertEqual(result['changes']['input_roles'], ['historical_fx.market_series_file'])
        self.assertEqual(result['changes']['fx'][0]['after']['path'], 'inputs/historical_fx-series.json')
        self.assertIn('fx_evidence', result['after']['evidence'])
        self.assertEqual(result['after']['evidence']['fx_evidence']['pointer'], '/fx_evidence')

    def rewrite_manifest(self, run, edit):
        path = run / 'analysis-run.json'
        manifest = json.loads(path.read_text())
        edit(manifest)
        path.write_text(json.dumps(manifest))

    def rewrite_payload(self, run, name, data):
        (run / name).write_bytes(data)
        def edit(manifest):
            manifest['files'][name].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            if name == 'result.json':
                manifest['output_sha256'] = manifest['files'][name]['sha256']
        self.rewrite_manifest(run, edit)

    def test_scope_date_currency_identity_and_semantics_disable_numerical_comparison(self):
        before = self.capture('before')
        for name, change, parameters, reason in [
            ('scope', lambda: None, {'by': 'account'}, 'scope_changed'),
            ('date', lambda: None, {'since': '2026-02-01'}, 'date_window_changed'),
            ('currency', lambda: self.portfolio['settings'].update(base_currency='EUR'), {}, 'reporting_currency_changed'),
            ('identity', lambda: self.portfolio['profile'].update(portfolio_id='other'), {}, 'portfolio_identity_changed'),
            ('semantics', lambda: self.snapshots[-1]['metadata']['rikdom_return_convention'].update(kind='price_return'), {}, 'method_or_semantics_changed'),
        ]:
            with self.subTest(name=name):
                saved_portfolio = json.loads(json.dumps(self.portfolio))
                saved_snapshots = json.loads(json.dumps(self.snapshots))
                change()
                if name == 'currency':
                    for row in self.snapshots:
                        row['base_currency'] = 'EUR'
                after = self.capture(name, **parameters)
                result = self.compare(before, after)
                self.assertIn(reason, result['compatibility']['reasons'])
                self.assertFalse(result['compatibility']['comparable'])
                self.assertEqual(result['deltas'], {})
                self.portfolio, self.snapshots = saved_portfolio, saved_snapshots

    def test_foreign_environment_and_method_are_inspected_without_replaying(self):
        before, after = self.capture('before'), self.capture('after')
        self.rewrite_manifest(after, lambda manifest: manifest['environment'].update(python='0.0'))
        result = self.compare(before, after)
        self.assertIn('recorded_environment_changed', result['compatibility']['reasons'])
        self.assertEqual(result['changes']['environment'], ['python'])
        self.assertEqual(result['deltas'], {})
        self.rewrite_manifest(after, lambda manifest: manifest['methods'].update(twr_method='future_method'))
        changed = json.loads((after / 'result.json').read_text())
        changed['twr_method'] = 'future_method'
        self.rewrite_payload(after, 'result.json', json.dumps(changed).encode())
        result = self.compare(before, after)
        self.assertIn('method_or_semantics_changed', result['compatibility']['reasons'])
        self.assertIn('twr_method', result['changes']['methods'])
        self.assertEqual(result['deltas'], {})

    def test_missing_fx_remains_unavailable_and_never_becomes_zero(self):
        self.historical_fx(stale=True)
        before, after = self.capture('before'), self.capture('after')
        result = self.compare(before, after)
        metric = result['deltas']['net_external_cashflow_base']
        self.assertIsNone(metric['before'])
        self.assertIsNone(metric['after'])
        self.assertIsNone(metric['delta'])
        self.assertEqual(result['coverage']['before']['fx_status'], 'unavailable')
        self.assertIsNone(result['coverage']['before']['history_coverage'])

    def test_rejects_malformed_tampered_omitted_and_unsupported_evidence_without_writes(self):
        from rikdom.analysis_runs import AnalysisRunError
        before = self.capture('before')
        cases = [
            ('tampered', lambda run: (run / 'inputs/portfolio.json').write_bytes(b'{}')),
            ('missing', lambda run: (run / 'inputs/snapshots.jsonl').unlink()),
            ('omitted', lambda run: self.rewrite_manifest(run, lambda m: m.update(replayable=False, omitted=['fx']))),
            ('version', lambda run: self.rewrite_manifest(run, lambda m: m.update(format_version='9.0'))),
            ('operation', lambda run: self.rewrite_manifest(run, lambda m: m.update(operation='aggregate'))),
            ('manifest_list', lambda run: (run / 'analysis-run.json').write_text('[]')),
            ('manifest_duplicate', lambda run: (run / 'analysis-run.json').write_text('{"format":"x","format":"y"}')),
            ('bad_result', lambda run: self.rewrite_payload(run, 'result.json', b'{}')),
            ('duplicate_result', lambda run: self.rewrite_payload(run, 'result.json', b'{"x":1,"x":2}')),
            ('torn_jsonl', lambda run: self.rewrite_payload(run, 'inputs/snapshots.jsonl', b'{"x": 1}')),
            ('overflow', lambda run: self.rewrite_payload(run, 'inputs/fx_history.jsonl', b'{"x": 1e999}\n')),
            ('missing_method', lambda run: self.rewrite_manifest(run, lambda m: m.pop('methods'))),
            ('missing_environment', lambda run: self.rewrite_manifest(run, lambda m: m.pop('environment'))),
            ('invalid_environment', lambda run: self.rewrite_manifest(run, lambda m: m.update(environment={}))),
            ('wrong_role', lambda run: self.rewrite_manifest(run, lambda m: m['files']['inputs/portfolio.json'].update(role='fx_history'))),
            ('unsafe', lambda run: self.rewrite_manifest(run, lambda m: m['files'].update({'../escape.json': m['files']['result.json']}))),
        ]
        for name, mutate in cases:
            with self.subTest(name=name):
                run = self.capture(name)
                mutate(run)
                inventory = self.inventory()
                with self.assertRaises(AnalysisRunError):
                    self.compare(before, run)
                self.assertEqual(self.inventory(), inventory)

    def test_self_consistent_recorded_result_is_not_certified_as_reproduced(self):
        before, after = self.capture('before'), self.capture('after')
        changed = json.loads((after / 'result.json').read_text())
        changed['end_value_base'] = 999
        self.rewrite_payload(after, 'result.json', json.dumps(changed).encode())
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'unresolved')
        self.assertFalse(result['replayed'])
        self.assertEqual(result['changes']['input_roles'], [])

    def test_reviewed_source_revisions_have_exact_captured_pointers(self):
        from rikdom.reviewed_imports import prepare_reviewed_import, retain_reviewed_import
        from rikdom.plugins import merge_activities
        raw = {'provider': 'synthetic', 'activities': [self.add_flow()]}
        self.portfolio['activities'] = []
        effective, report, state = prepare_reviewed_import(self.portfolio, raw)
        self.assertTrue(report['ok'])
        self.portfolio, _ = merge_activities(self.portfolio, effective)
        retain_reviewed_import(self.portfolio, raw, state)
        before = self.capture('before')
        effective, report, state = prepare_reviewed_import(self.portfolio, raw, {
            'version': 1, 'decisions': [{'id': 'review', 'collection': 'activities',
                'entity_id': 'flow', 'changes': {'money': {'amount': 5, 'currency': 'USD'}},
                'evidence': {'kind': 'user_declaration', 'source_ref': 'synthetic-review'}}]})
        self.assertTrue(report['ok'])
        self.portfolio, _ = merge_activities(self.portfolio, effective)
        retain_reviewed_import(self.portfolio, raw, state)
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'unresolved')
        revision = result['after']['source_reviews'][1]
        self.assertRegex(revision['source_revision'], '[a-f0-9]{64}')
        self.assertEqual(revision['evidence']['pointer'], '/extensions/rikdom_reviewed_imports/revisions/1')
        self.assertEqual(result['changes']['activities']['modified'][0]['id'], 'flow')

    def test_cli_outputs_same_contract_and_does_not_create_default_workspace(self):
        import os
        before, after = self.capture('before'), self.capture('after')
        out, err = io.StringIO(), io.StringIO()
        cwd = Path.cwd()
        os.chdir(self.root)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = main(['compare-analysis', '--before', str(before), '--after', str(after)])
        finally:
            os.chdir(cwd)
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(json.loads(out.getvalue()), self.compare(before, after))
        self.assertFalse((self.root / 'data').exists())
        self.assertFalse((self.root / 'out').exists())

    def test_cli_invalid_evidence_has_no_json_success_or_writes(self):
        before = self.capture('before')
        out, err = io.StringIO(), io.StringIO()
        inventory = self.inventory()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['compare-analysis', '--before', str(before), '--after', str(self.root / 'missing')])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), '')
        self.assertIn('Analysis comparison failed', err.getvalue())
        self.assertEqual(self.inventory(), inventory)

    def test_fx_configuration_change_is_not_a_controlled_vintage_revision(self):
        self.historical_fx()
        before = self.capture('before')
        config_path = self.extra_inputs['historical_fx']
        config = json.loads(config_path.read_text())
        config['max_age_seconds'] = 172800
        config_path.write_text(json.dumps(config))
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'unresolved')

    def test_recorded_coverage_uses_retained_statement_contract_and_pointers(self):
        from rikdom.plugins import merge_import_diagnostics
        self.portfolio = merge_import_diagnostics(self.portfolio, {'provider': 'synthetic', 'metadata': {
            'rikdom_import_diagnostics': {'version': 1, 'document_fingerprint': 'synthetic',
                'history_coverage': [{'scope': 'synthetic', 'status': 'partial', 'event_types': ['contribution'],
                                      'reasons': ['Synthetic incomplete history']}],
                'unsupported_events': []}}})
        before = self.capture('before')
        result = self.compare(before, before)
        self.assertEqual(result['coverage']['before']['history_coverage'][0]['status'], 'partial')
        self.assertIn('history_coverage', result['before']['evidence'])

    def test_identical_foreign_runtime_is_still_explicitly_incompatible(self):
        before, after = self.capture('before'), self.capture('after')
        for run in (before, after):
            self.rewrite_manifest(run, lambda m: m['environment'].update(python='0.0'))
        result = self.compare(before, after)
        self.assertIn('recorded_runtime_unsupported', result['compatibility']['reasons'])
        self.assertEqual(result['before']['runtime_compatibility']['mismatches'], ['python'])
        self.assertEqual(result['deltas'], {})

    def test_actual_method_change_is_incompatible(self):
        self.add_flow()
        before = self.capture('before')
        flow = self.root / 'flow-valuations.json'
        flow.write_text(json.dumps({'version': 1, 'scope': 'portfolio', 'base_currency': 'USD',
            'rounding_tolerance_base': 0.0001, 'valuations': [{
                'timestamp': '2026-06-01T00:00:00Z', 'base_currency': 'USD',
                'pre_flow_value_base': 100, 'post_flow_value_base': 110, 'source': 'synthetic'}]}))
        self.extra_inputs['flow_valuations'] = flow
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertIn('method_or_semantics_changed', result['compatibility']['reasons'])
        self.assertEqual(result['deltas'], {})

    def test_cutoff_only_fx_vintage_change_is_controlled(self):
        series_path = self.historical_fx()
        observations = self.series['series'][0]['observations']
        observations.append({**observations[0], 'id': 'revised', 'value': 5.5,
                             'retrieved_at': '2026-06-02T00:00:00Z', 'supersedes': 'original'})
        series_path.write_text(json.dumps(self.series))
        config_path = self.extra_inputs['historical_fx']
        config = json.loads(config_path.read_text())
        config['retrieved_before'] = '2026-06-01T00:00:00Z'
        config_path.write_text(json.dumps(config))
        before = self.capture('before')
        config['retrieved_before'] = '2026-06-02T00:00:00Z'
        config_path.write_text(json.dumps(config))
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'controlled_fx_revision')
        self.assertEqual(result['deltas']['net_external_cashflow_base']['delta'], 5)

    def test_differing_capture_cutoff_prevents_controlled_source_isolation(self):
        self.add_flow()
        before = self.capture('before')
        corrected = self.add_flow(5, 'corrected')
        corrected['extensions'] = {'rikdom_correction': {
            'version': 1, 'supersedes_activity_id': 'flow', 'reason': 'Reviewed source correction'}}
        after = self.capture('after', analysis_as_of='2027-01-02T00:00:00Z')
        result = self.compare(before, after)
        self.assertEqual(result['changes']['parameters'], ['analysis_as_of'])
        self.assertEqual(result['explanation']['classification'], 'unresolved')

    def test_stale_fx_and_unspecified_return_semantics_preserve_unknowns(self):
        self.historical_fx()
        self.portfolio['activities'][0]['effective_at'] = '2026-06-10T00:00:00Z'
        before = self.capture('before')
        result = self.compare(before, before)
        self.assertIsNone(result['deltas']['net_external_cashflow_base']['delta'])
        self.assertEqual(result['coverage']['before']['fx_status'], 'unavailable')
        self.assertEqual(json.loads((before / 'result.json').read_text())['fx_evidence'][0]['reason'], 'maximum_age_exceeded')
        self.extra_inputs = {}
        self.portfolio['activities'] = []
        for snapshot in self.snapshots:
            snapshot.pop('metadata')
        unspecified = self.capture('unspecified')
        result = self.compare(unspecified, unspecified)
        self.assertIsNone(result['deltas']['twr_return_pct']['delta'])

    def test_restored_v2_archives_compare_offline_without_writes(self):
        import socket
        from unittest.mock import patch
        from rikdom.analysis_runs import export_analysis_run, restore_analysis_run
        before = self.capture('before')
        bundle, restored = self.root / 'run.zip', self.root / 'restored'
        export_analysis_run(before, bundle)
        restore_analysis_run(bundle, restored)
        inventory = self.inventory()
        with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            result = self.compare(before, restored)
        self.assertEqual(result['explanation']['classification'], 'unchanged')
        self.assertEqual(result['before']['input_sha256'], result['after']['input_sha256'])
        self.assertEqual(self.inventory(), inventory)

    def test_multiple_independent_corrections_are_not_isolated_as_one_driver(self):
        self.add_flow(10, 'one')
        self.add_flow(10, 'two')
        before = self.capture('before')
        for target in ('one', 'two'):
            corrected = self.add_flow(5, target + '-corrected')
            corrected['extensions'] = {'rikdom_correction': {
                'version': 1, 'supersedes_activity_id': target, 'reason': 'Reviewed source correction'}}
        after = self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['explanation']['classification'], 'unresolved')

    def test_missing_nested_fx_contract_fields_are_rejected_without_writes(self):
        from rikdom.analysis_runs import AnalysisRunError
        self.historical_fx()
        before, after = self.capture('before'), self.capture('after')
        config = json.loads((after / 'inputs/historical_fx.json').read_text())
        config.pop('retrieved_before')
        self.rewrite_payload(after, 'inputs/historical_fx.json', json.dumps(config).encode())
        inventory = self.inventory()
        with self.assertRaises(AnalysisRunError):
            self.compare(before, after)
        self.assertEqual(self.inventory(), inventory)

    def test_unknown_recorded_method_is_inspectable_but_never_numerically_comparable(self):
        before, after = self.capture('before'), self.capture('after')
        for run in (before, after):
            self.rewrite_manifest(run, lambda m: m['methods'].update(twr_method='future_method'))
            result = json.loads((run / 'result.json').read_text())
            result['twr_method'] = 'future_method'
            self.rewrite_payload(run, 'result.json', json.dumps(result).encode())
        result = self.compare(before, after)
        self.assertIn('method_evidence_unsupported', result['compatibility']['reasons'])
        self.assertEqual(result['deltas'], {})

    def test_historical_valuation_evidence_is_read_without_replay_and_rejects_omission(self):
        from rikdom.analysis_runs import AnalysisRunError
        sample = Path('data-sample/historical-valuation-replay')
        self.portfolio = json.loads((sample / 'portfolio.json').read_text())
        self.extra_inputs['historical_valuations'] = sample / 'replay.json'
        before, after = self.capture('before'), self.capture('after')
        result = self.compare(before, after)
        self.assertEqual(result['coverage']['before']['valuation_status'], 'complete')
        self.assertEqual(result['deltas']['start_value_base']['before'], 135)
        self.assertEqual(result['deltas']['start_value_base']['delta'], 0)
        config = json.loads((after / 'inputs/historical_valuations.json').read_text())
        config.pop('snapshots')
        self.rewrite_payload(after, 'inputs/historical_valuations.json', json.dumps(config).encode())
        with self.assertRaises(AnalysisRunError):
            self.compare(before, after)
