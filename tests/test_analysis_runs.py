from __future__ import annotations

import io
import json
import shutil
import zipfile
import socket
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rikdom.cli import main


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class AnalysisRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.portfolio = self.root / 'portfolio.json'
        portfolio = json.loads(Path('tests/fixtures/portfolio.json').read_text())
        portfolio['settings']['base_currency'] = 'USD'
        portfolio['holdings'] = []
        portfolio['activities'] = []
        self.portfolio.write_text(json.dumps(portfolio))
        self.snapshots = self.root / 'snapshots.jsonl'
        self.snapshots.write_text('\n'.join(json.dumps({
            'timestamp': date, 'base_currency': 'USD',
            'totals': {'portfolio_value_base': value, 'by_asset_class': {'cash': value}},
        }) for date, value in [('2026-01-01T00:00:00Z', 100), ('2026-12-31T00:00:00Z', 110)]) + '\n')
        self.fx = self.root / 'fx.jsonl'
        self.fx.write_text('')
        self.run = self.root / 'run'

    def capture(self, *extra):
        code, out, err = run_cli('capture-analysis', '--portfolio', str(self.portfolio),
            '--snapshots', str(self.snapshots), '--fx-history', str(self.fx),
            '--output', str(self.run), *extra)
        self.assertEqual((code, err), (0, ''))
        return json.loads(out)

    def test_mutating_originals_cannot_change_restored_offline_financial_results(self):
        self.capture()
        expected = json.loads((self.run / 'result.json').read_text())
        self.assertEqual(expected['twr_pct'], 10)
        self.portfolio.write_text('{}')
        self.snapshots.unlink()
        bundle = self.root / 'run.zip'
        self.assertEqual(run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle))[0], 0)
        restored = self.root / 'restored'
        self.assertEqual(run_cli('restore-analysis', '--bundle', str(bundle), '--output', str(restored))[0], 0)
        with patch.object(socket, 'create_connection', side_effect=AssertionError('offline')):
            code, out, err = run_cli('replay-analysis', '--run', str(restored))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out), expected)

    def test_v2_bundle_replay_export_preserves_existing_performance_result(self):
        self.capture()
        expected = json.loads((self.run / 'result.json').read_text())
        bundle, restored = self.root / 'performance.zip', self.root / 'reproduced'
        self.assertEqual(run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle))[0], 0)
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(json.loads(archive.read('rikdom-export.json'))['format_version'], '2.0.0')
        code, out, err = run_cli('replay-export', '--bundle', str(bundle), '--restore-dir', str(restored))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['status'], 'reproduced')
        self.assertEqual(json.loads(out)['result'], expected)
        self.assertEqual(json.loads((restored / 'result.json').read_text()), expected)

    def test_missing_and_changed_input_refuse_replay(self):
        self.capture()
        source = self.run / 'inputs' / 'portfolio.json'
        original = source.read_bytes()
        source.write_bytes(original + b' ')
        self.assertIn('changed', run_cli('replay-analysis', '--run', str(self.run))[2])
        source.unlink()
        code, _, err = run_cli('replay-analysis', '--run', str(self.run))
        self.assertEqual(code, 1)
        self.assertIn('missing', err)

    def test_incompatible_environment_refuses_before_calculation(self):
        self.capture()
        path = self.run / 'analysis-run.json'
        manifest = json.loads(path.read_text())
        manifest['environment']['python'] = '0.0'
        path.write_text(json.dumps(manifest))
        code, _, err = run_cli('replay-analysis', '--run', str(self.run))
        self.assertEqual(code, 1)
        self.assertIn('incompatible', err)

    def test_redacted_preview_and_export_omit_data_and_refuse_replay(self):
        self.capture()
        bundle = self.root / 'share.zip'
        code, out, err = run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle), '--redacted', '--dry-run')
        self.assertEqual((code, err), (0, ''))
        self.assertFalse(bundle.exists())
        self.assertFalse(json.loads(out)['replayable'])
        self.assertEqual(run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle), '--redacted')[0], 0)
        restored = self.root / 'shared'
        self.assertEqual(run_cli('restore-analysis', '--bundle', str(bundle), '--output', str(restored))[0], 0)
        code, _, err = run_cli('replay-analysis', '--run', str(restored))
        self.assertEqual(code, 1)
        self.assertIn('omitted', err)

    def test_malformed_required_jsonl_is_not_certified_by_capture(self):
        self.snapshots.write_text(self.snapshots.read_text() + '{torn')
        code, _, err = run_cli('capture-analysis', '--portfolio', str(self.portfolio),
            '--snapshots', str(self.snapshots), '--fx-history', str(self.fx), '--output', str(self.run))
        self.assertEqual(code, 1)
        self.assertIn('snapshots', err)
        self.assertFalse(self.run.exists())

    def test_missing_required_benchmark_prevents_complete_capture(self):
        policy = self.root / 'policy.json'
        policy.write_text(json.dumps({'benchmarks': [{'id': 'missing', 'kind': 'index', 'currency': 'USD'}],
            'strategic_allocation': {'targets': [{'benchmark_id': 'missing', 'weight_pct': 100}]}}))
        code, _, err = run_cli('capture-analysis', '--portfolio', str(self.portfolio),
            '--snapshots', str(self.snapshots), '--fx-history', str(self.fx), '--output', str(self.run),
            '--policy', str(policy), '--benchmarks-dir', str(self.root))
        self.assertEqual(code, 1)
        self.assertIn('benchmark', err)
        self.assertFalse(self.run.exists())

    def test_historical_inputs_include_nested_caches_and_benchmark_series(self):
        sample = Path('data-sample/historical-valuation-replay')
        original = self.root / 'original'
        shutil.copytree(sample, original)
        benchmarks = original / 'benchmarks'
        benchmarks.mkdir()
        (benchmarks / 'index.jsonl').write_text(''.join(json.dumps({
            'as_of': date, 'level': level, 'currency': 'BRL', 'return_convention': 'total_return',
            'source': 'manual:synthetic'}) + '\n' for date, level in [
                ('2026-01-02T00:00:00Z', 100), ('2026-01-06T00:00:00Z', 110)]))
        (original / 'policy.json').write_text(json.dumps({'benchmarks': [
            {'id': 'index', 'kind': 'index', 'currency': 'BRL'}],
            'strategic_allocation': {'targets': [{'benchmark_id': 'index', 'weight_pct': 100}]}}))
        code, out, err = run_cli('capture-analysis', '--portfolio', str(original / 'portfolio.json'),
            '--snapshots', str(self.snapshots), '--fx-history', str(self.fx), '--output', str(self.run),
            '--historical-valuations', str(original / 'replay.json'),
            '--historical-fx', str(original / 'historical-fx.json'),
            '--flow-valuations', str(original / 'flow-valuations.json'),
            '--policy', str(original / 'policy.json'), '--benchmarks-dir', str(benchmarks))
        self.assertEqual((code, err), (0, ''))
        expected = json.loads((self.run / 'result.json').read_text())
        self.assertEqual(expected['start_value_base'], 135)
        self.assertEqual(expected['end_value_base'], 254)
        shutil.rmtree(original)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('offline')):
            code, out, err = run_cli('replay-analysis', '--run', str(self.run))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out), expected)
        nested = self.run / 'inputs/historical_valuations-series.json'
        nested.unlink()
        self.assertEqual(run_cli('replay-analysis', '--run', str(self.run))[0], 1)

    def test_corrupted_bundle_restore_keeps_previous_directory(self):
        self.capture()
        bundle = self.root / 'run.zip'
        run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle))
        bad = self.root / 'bad.zip'
        with zipfile.ZipFile(bundle) as src, zipfile.ZipFile(bad, 'w') as dst:
            for name in src.namelist():
                data = src.read(name)
                dst.writestr(name, data + b' ' if name.endswith('/portfolio.json') else data)
        restored = self.root / 'restore'
        self.assertEqual(run_cli('restore-analysis', '--bundle', str(bad), '--output', str(restored))[0], 1)
        self.assertFalse(restored.exists())
        code, _, err = run_cli('replay-export', '--bundle', str(bad), '--restore-dir', str(restored))
        self.assertEqual(code, 1)
        self.assertIn('mismatch', err)
        self.assertFalse(restored.exists())
        restored.mkdir()
        sentinel = restored / 'keep'
        sentinel.write_text('preserved')
        self.assertEqual(run_cli('restore-analysis', '--bundle', str(bundle), '--output', str(restored))[0], 1)
        self.assertEqual(sentinel.read_text(), 'preserved')

    def test_mismatched_expected_result_cannot_claim_reproduction(self):
        self.capture()
        manifest_path = self.run / 'analysis-run.json'
        manifest = json.loads(manifest_path.read_text())
        # A self-consistent changed expected result must still be compared to calculation.
        import hashlib
        changed = b'{"financial": "wrong"}\n'
        (self.run / 'result.json').write_bytes(changed)
        sha = hashlib.sha256(changed).hexdigest()
        manifest['files']['result.json'].update(bytes=len(changed), sha256=sha)
        manifest['output_sha256'] = sha
        manifest_path.write_text(json.dumps(manifest))
        code, _, err = run_cli('replay-analysis', '--run', str(self.run))
        self.assertEqual(code, 1)
        self.assertIn('differs', err)

        bundle, restored = self.root / 'wrong-result.zip', self.root / 'restored'
        self.assertEqual(run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle))[0], 0)
        code, _, err = run_cli('replay-export', '--bundle', str(bundle), '--restore-dir', str(restored))
        self.assertEqual(code, 1)
        self.assertIn('differs', err)
        self.assertFalse(restored.exists())
        self.assertEqual(list(self.root.glob('.rikdom-restore-*')), [])

    def test_replay_uses_the_verified_bytes_when_run_changes_during_calculation(self):
        self.capture()
        from rikdom.cli import cmd_performance
        expected = json.loads((self.run / 'result.json').read_bytes())
        captured = self.run / 'inputs/snapshots.jsonl'

        def change_original_then_calculate(args):
            captured.write_bytes(captured.read_bytes().replace(b'110', b'999'))
            return cmd_performance(args)

        with patch('rikdom.cli.cmd_performance', side_effect=change_original_then_calculate):
            code, out, err = run_cli('replay-analysis', '--run', str(self.run))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out), expected)

    def test_capture_never_bootstraps_missing_default_inputs(self):
        data = self.root / 'uncreated-data'
        code, _, err = run_cli('capture-analysis', '--data-dir', str(data), '--output', str(self.run))
        self.assertEqual(code, 1)
        self.assertIn('missing', err)
        self.assertFalse(data.exists())
        self.assertFalse(self.run.exists())

    def test_analysis_bundle_verifies_but_v1_import_refuses_without_writes(self):
        self.capture()
        bundle = self.root / 'analysis.zip'
        self.assertEqual(run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle))[0], 0)
        self.assertEqual(run_cli('verify-export', '--bundle', str(bundle))[0], 0)
        data = self.root / 'uncreated-data'
        code, _, err = run_cli('import-export', '--bundle', str(bundle), '--data-dir', str(data))
        self.assertEqual(code, 1)
        self.assertIn('restore-analysis', err)
        self.assertFalse(data.exists())

    def test_license_omission_retains_hash_and_refuses_replay(self):
        self.capture()
        bundle = self.root / 'restricted.zip'
        code, out, err = run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle),
            '--omit-input', 'fx_history', '--omission-reason', 'license')
        self.assertEqual((code, err), (0, ''))
        preview = json.loads(out)
        self.assertFalse(preview['replayable'])
        omitted = preview['manifest']['omitted'][0]
        self.assertEqual(omitted['reason'], 'license')
        self.assertRegex(omitted['sha256'], '[a-f0-9]{64}')
        restored = self.root / 'restricted'
        self.assertEqual(run_cli('restore-analysis', '--bundle', str(bundle), '--output', str(restored))[0], 0)
        self.assertFalse((restored / 'inputs/fx_history.jsonl').exists())
        code, _, err = run_cli('replay-analysis', '--run', str(restored))
        self.assertEqual(code, 1)
        self.assertIn('omitted', err)

        target = self.root / 'cannot-reproduce'
        code, _, err = run_cli('replay-export', '--bundle', str(bundle), '--restore-dir', str(target))
        self.assertEqual(code, 1)
        self.assertIn('omitted', err)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob('.rikdom-restore-*')), [])

    def test_replay_export_preserves_existing_directory_and_dangling_symlink(self):
        self.capture()
        bundle = self.root / 'run.zip'
        self.assertEqual(run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle))[0], 0)
        target = self.root / 'existing'
        target.mkdir()
        sentinel = target / 'keep'
        sentinel.write_text('preserved')
        link = self.root / 'dangling'
        link.symlink_to(self.root / 'missing')
        for destination in (target, link):
            with self.subTest(destination=destination):
                code, _, err = run_cli('replay-export', '--bundle', str(bundle),
                                       '--restore-dir', str(destination))
                self.assertEqual(code, 1)
                self.assertIn('must not exist', err)
        self.assertEqual(sentinel.read_text(), 'preserved')
        self.assertTrue(link.is_symlink())
        self.assertFalse(link.resolve().exists())

    def test_replay_export_incompatible_environment_leaves_no_workspace(self):
        self.capture()
        manifest_path = self.run / 'analysis-run.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['environment']['python'] = '0.0'
        manifest_path.write_text(json.dumps(manifest))
        from rikdom.export_bundle import write_analysis_bundle
        bundle, target = self.root / 'incompatible.zip', self.root / 'restored'
        write_analysis_bundle(bundle, {
            path.relative_to(self.run).as_posix(): path.read_bytes()
            for path in self.run.rglob('*') if path.is_file()
        })
        code, _, err = run_cli('replay-export', '--bundle', str(bundle), '--restore-dir', str(target))
        self.assertEqual(code, 1)
        self.assertIn('incompatible', err)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob('.rikdom-restore-*')), [])

    def test_replay_export_interrupted_restore_removes_staging(self):
        self.capture()
        bundle, target = self.root / 'run.zip', self.root / 'restored'
        self.assertEqual(run_cli('export-analysis', '--run', str(self.run), '--output', str(bundle))[0], 0)
        original_write = Path.write_bytes

        def interrupted(path, data):
            if path.name == 'result.json':
                raise OSError('interrupted restore')
            return original_write(path, data)

        with patch.object(Path, 'write_bytes', interrupted):
            code, _, err = run_cli('replay-export', '--bundle', str(bundle), '--restore-dir', str(target))
        self.assertEqual(code, 1)
        self.assertIn('interrupted restore', err)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob('.rikdom-restore-*')), [])

    def test_capture_rejects_unknown_parameters_and_keeps_existing_directory(self):
        self.capture()
        before = (self.run / 'result.json').read_bytes()
        code, _, _ = run_cli('capture-analysis', '--portfolio', str(self.portfolio), '--output', str(self.run), '--unknown-input', 'foo')
        self.assertNotEqual(code, 0)
        self.assertEqual((self.run / 'result.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
