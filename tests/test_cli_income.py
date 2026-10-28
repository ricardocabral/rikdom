import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from rikdom.cli import main


def ledger(**fields):
    return {'schema_version': '2.0.0', 'activities': [
        {'id': 'a', 'event_type': 'dividend', 'status': 'posted', 'effective_at': '2026-01-01T00:00:00Z',
         'money': {'amount': 100, 'currency': 'USD'},
         'withholding_tax': {'amount': 10, 'currency': 'USD'}, **fields}]}


class CliIncomeTests(unittest.TestCase):
    def run_income(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(['income', *map(str, args)])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_artifacts_stdout_and_canonical_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            data.mkdir()
            canonical = data / 'portfolio.json'
            canonical.write_text(json.dumps(ledger()))
            for name in ('snapshots.jsonl', 'import_log.jsonl', 'fx_rates.jsonl'):
                (data / name).write_text('unchanged\n')
            before = {p: p.read_bytes() for p in data.iterdir()}
            rc, out, err = self.run_income('--data-dir', data, '--out-root', root / 'out')
            self.assertEqual((rc, err), (0, ''))
            report = json.loads(out)
            self.assertEqual(report['monthly'][0]['net']['total'], 90)
            reports = root / 'out' / 'reports'
            self.assertEqual(json.loads((reports / 'income.json').read_text()), report)
            markdown = (reports / 'income.md').read_text()
            self.assertIn('2026-01', markdown)
            self.assertIn('USD', markdown)
            self.assertIn('90', markdown)
            self.assertEqual({p: p.read_bytes() for p in data.iterdir()}, before)

    def test_formats_explicit_paths_and_inclusive_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / 'source.json'
            canonical.write_text(json.dumps(ledger()))
            for format, names in [('json', {'income.json'}), ('markdown', {'income.md'}), ('both', {'income.json', 'income.md'})]:
                destination = root / format
                rc, out, err = self.run_income('--portfolio', canonical, '--out-dir', destination,
                    '--format', format, '--start', '2026-01-01', '--end', '2026-01-01')
                self.assertEqual((rc, err), (0, ''))
                self.assertEqual(len(json.loads(out)['events']), 1)
                self.assertEqual({p.name for p in destination.iterdir()}, names)

    def test_named_workspace_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            selected = data / 'portfolios' / 'paper'
            selected.mkdir(parents=True)
            (selected / 'portfolio.json').write_text(json.dumps(ledger()))
            (data / 'portfolio.json').write_text('do not read')
            (data / 'portfolio_registry.json').write_text(json.dumps({'portfolios': [{'name': 'paper'}]}))
            rc, out, err = self.run_income('--data-dir', data, '--out-root', root / 'out', '--portfolio-name', 'paper')
            self.assertEqual((rc, err), (0, ''))
            self.assertEqual(json.loads(out)['events'][0]['gross'], 100)
            self.assertTrue((root / 'out' / 'reports' / 'paper' / 'income.json').exists())
            self.assertFalse((root / 'out' / 'reports' / 'income.json').exists())
            self.assertEqual((data / 'portfolio.json').read_text(), 'do not read')

    def test_invalid_contract_dates_or_amount_create_no_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / 'portfolio.json'
            destination = root / 'reports'
            cases = [(ledger(), ['--start', '2026-02-01', '--end', '2026-01-01']),
                     ({'schema_version': '99.0.0'}, []), (ledger(money=None), []),
                     (ledger(money={'amount': float('nan'), 'currency': 'USD'}), [])]
            for p, args in cases:
                canonical.write_text(json.dumps(p))
                before = canonical.read_bytes()
                rc, out, err = self.run_income('--portfolio', canonical, '--out-dir', destination, *args)
                self.assertEqual(rc, 1)
                self.assertEqual(out, '')
                self.assertTrue(err)
                self.assertFalse(destination.exists())
                self.assertEqual(canonical.read_bytes(), before)

    def test_missing_default_input_does_not_bootstrap_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rc, out, err = self.run_income('--data-dir', root / 'absent', '--out-root', root / 'out')
            self.assertEqual(rc, 1)
            self.assertFalse((root / 'absent').exists())
            self.assertFalse((root / 'out').exists())

    def test_output_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / 'income.json'
            canonical.write_text(json.dumps(ledger()))
            before = canonical.read_bytes()
            rc, out, err = self.run_income('--portfolio', canonical, '--out-dir', root)
            self.assertEqual(rc, 1)
            self.assertEqual(canonical.read_bytes(), before)
            self.assertFalse((root / 'income.md').exists())
