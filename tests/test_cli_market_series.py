import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from rikdom.cli import main
from tests.test_market_series import document


class CliMarketSeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'input.json'
        self.path.write_text(json.dumps(document()))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = main(['market-series', *map(str, args)])
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def lookup(self, *args):
        return self.run_cli('--input', self.path, '--series', 'example-price', '--as-of',
                            '2026-01-03T16:00:00Z', '--max-age-seconds', '86400', *args)

    def test_repeated_json_provenance_and_all_files_unchanged(self):
        data = self.root / 'data'
        data.mkdir()
        for name in ['portfolio.json', 'activities.jsonl', 'snapshots.jsonl', 'fx_rates.jsonl']:
            (data / name).write_text('canonical bytes remain unchanged\n')
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            first = self.lookup()
            self.assertEqual(first, self.lookup())
            self.assertEqual((first[0], first[2]), (0, ''))
            result = json.loads(first[1])
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['observation']['value'], 100)
            self.assertEqual(result['observation']['source'], 'manual:example')
            self.assertEqual(result['series']['license']['name'], 'CC0-1.0')
            self.assertEqual({str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)
            self.assertFalse((self.root / 'out').exists())
        finally:
            os.chdir(original_cwd)

    def test_missing_stale_and_knowledge_cutoff_are_json_results(self):
        for args, status in [(['--series', 'unknown'], 'missing'),
                             (['--max-age-seconds', '1'], 'stale'),
                             (['--retrieved-before', '2026-01-02T16:00:00Z'], 'missing')]:
            rc, out, err = self.lookup(*args)
            self.assertEqual((rc, err), (0, ''))
            self.assertEqual(json.loads(out)['status'], status)

    def test_invalid_input_or_query_has_nonzero_exit_and_no_json(self):
        for args in [('--input', self.root / 'absent'), ('--max-age-seconds', '-1'),
                     ('--max-age-seconds', 'nan'), ('--as-of', '2026-01-03')]:
            rc, out, err = self.lookup(*args)
            self.assertEqual(rc, 1)
            self.assertEqual(out, '')
            self.assertTrue(err)
        self.path.write_text('{bad')
        rc, out, err = self.lookup()
        self.assertEqual((rc, out), (1, ''))
        self.assertTrue(err)

    def test_as_of_and_max_age_are_required(self):
        for args in [[], ['--as-of', '2026-01-03T00:00:00Z'], ['--max-age-seconds', '1']]:
            rc, out, err = self.run_cli('--input', self.path, '--series', 'example-price', *args)
            self.assertEqual(rc, 2)
            self.assertEqual(out, '')
            self.assertTrue(err)
