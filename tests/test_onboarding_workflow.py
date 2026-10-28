"""Exercise the beginner workflow against tracked samples without network access."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rikdom.cli import main


ROOT = Path(__file__).resolve().parents[1]


class OnboardingWorkflowTests(unittest.TestCase):
    def bootstrap(self, data, out):
        subprocess.run(['make', 'bootstrap', f'DATA_DIR={data}', f'OUT_DIR={out}'],
                       cwd=ROOT, check=True, capture_output=True, text=True)

    def test_bootstrap_seeds_fx_and_preserves_existing_workspace(self):
        # Omitting FX from bootstrap breaks the offline snapshot path.
        with tempfile.TemporaryDirectory() as tmp:
            data, out = Path(tmp) / 'sample-data', Path(tmp) / 'sample-out'
            self.bootstrap(data, out)
            self.assertTrue((data / 'fx_rates.jsonl').exists(), 'bootstrap must seed local FX')
            self.assertEqual((data / 'fx_rates.jsonl').read_bytes(),
                             (ROOT / 'data-sample/fx_rates.jsonl').read_bytes())
            for path in data.rglob('*'):
                if path.is_file():
                    path.write_bytes(path.read_bytes() + b'\n')
            before = {p: p.read_bytes() for p in data.rglob('*') if p.is_file()}
            self.bootstrap(data, out)
            self.assertEqual({p: p.read_bytes() for p in data.rglob('*') if p.is_file()}, before)
            self.assertFalse(out.exists())

    def test_sample_import_to_income_snapshot_and_fallback_report_offline(self):
        # Catch accidental writes during preview, duplicate events on replay,
        # invented net income, or a workflow that silently starts fetching data.
        with tempfile.TemporaryDirectory() as tmp, \
                patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
                patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
                patch.dict(os.environ, {'RIKDOM_DISABLE_QUARTO': '1'}):
            data, out = Path(tmp) / 'data', Path(tmp) / 'out'
            self.bootstrap(data, out)

            def run(command, *args):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main([command, '--data-dir', str(data), '--out-root', str(out), *args])
                self.assertEqual(code, 0, stderr.getvalue() + stdout.getvalue())
                return stdout.getvalue()

            statement = ['--plugin', 'csv-generic', '--input', str(ROOT / 'data-sample/sample_statement.csv'),
                         '--plugins-dir', str(ROOT / 'plugins')]
            before = {p: p.read_bytes() for p in data.rglob('*') if p.is_file()}
            preview = json.loads(run('import-statement', *statement, '--dry-run', '--reconcile'))
            self.assertFalse(preview['write'])
            self.assertEqual(preview['dry_run_diff']['summary']['holdings']['create'], 2)
            self.assertEqual(preview['dry_run_diff']['summary']['activities']['create'], 3)
            self.assertEqual({p: p.read_bytes() for p in data.rglob('*') if p.is_file()}, before)
            self.assertFalse(out.exists())

            applied = json.loads(run('import-statement', *statement, '--write', '--reconcile'))
            self.assertEqual(applied['holdings']['inserted'], 2)
            self.assertEqual(applied['activities']['inserted'], 3)
            portfolio_before_replay = json.loads((data / 'portfolio.json').read_text())
            replay = json.loads(run('import-statement', *statement, '--write', '--reconcile'))
            self.assertEqual(replay['holdings'], {'inserted': 0, 'updated': 0, 'skipped': 2})
            self.assertEqual(replay['activities'], {'inserted': 0, 'updated': 0, 'skipped': 3})
            self.assertEqual(json.loads((data / 'portfolio.json').read_text()), portfolio_before_replay)
            self.assertEqual(len((data / 'import_log.jsonl').read_text().splitlines()), 2)
            self.assertEqual(applied['import_diagnostics']['history_coverage'][0]['status'], 'unknown')
            reports = out / 'reports'
            for name in ('holding_trust.json', 'holding_trust.md', 'reconciliation.json', 'reconciliation.md'):
                self.assertTrue((reports / name).is_file(), name)
            trust = json.loads((reports / 'holding_trust.json').read_text())
            self.assertTrue(trust['invariant']['matches'])
            reconciliation = json.loads((reports / 'reconciliation.json').read_text())
            self.assertEqual(reconciliation['coverage_summary']['by_status']['unknown'], 1)
            self.assertEqual(reconciliation['quantity_summary']['not_computable'], 4)
            run('validate')

            snapshots_before = (data / 'snapshots.jsonl').read_bytes()
            fx_before = (data / 'fx_rates.jsonl').read_bytes()
            run('snapshot', '--no-fx-auto-ingest', '--timestamp', '2026-04-21T10:00:00Z')
            snapshots_after = (data / 'snapshots.jsonl').read_bytes()
            self.assertTrue(snapshots_after.startswith(snapshots_before))
            self.assertEqual(len(snapshots_after.splitlines()), len(snapshots_before.splitlines()) + 1)
            latest = json.loads(snapshots_after.splitlines()[-1])
            self.assertEqual(latest['metadata']['fx_lock']['rates_to_base']['USD'], 5.25)
            self.assertEqual((data / 'fx_rates.jsonl').read_bytes(), fx_before)

            canonical = {p: p.read_bytes() for p in data.rglob('*') if p.is_file()}
            income = json.loads(run('income', '--start', '2026-01-01', '--end', '2026-12-31'))
            self.assertEqual([(r['currency'], r['gross']['total']) for r in income['yearly']],
                             [('BRL', 141.7), ('USD', 1.2)])
            self.assertEqual(len(income['events']), 3)
            self.assertNotIn('act-broker-reimb-2026-03', [r['activity_id'] for r in income['events']])
            self.assertTrue(all(r['net'] is None and r['withholding'] is None for r in income['events']))
            self.assertEqual(len(income['diagnostics']), 3)
            self.assertEqual(json.loads((reports / 'income.json').read_text()), income)
            self.assertTrue((reports / 'income.md').is_file())
            run('viz', '--plugins-dir', str(ROOT / 'plugins'))
            for name in ('dashboard.html', 'portfolio-report.html'):
                html = (out / name).read_text()
                self.assertIn('Fallback Portfolio Report', html)
                self.assertIn('Data quality', html)
            self.assertEqual({p: p.read_bytes() for p in data.rglob('*') if p.is_file()}, canonical)
