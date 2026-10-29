"""File workflow preserves inputs until explicitly applying a validated event."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rikdom.cli import main
from tests.test_market_events import AS_OF, document, portfolio, split_review


class MarketEventsCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.portfolio = self.root / 'portfolio.json'
        self.events = self.root / 'events.json'
        self.review = self.root / 'review.json'
        for path, value in ((self.portfolio, portfolio()), (self.events, document()), (self.review, split_review())):
            path.write_text(json.dumps(value))

    def invoke(self, action, *extra):
        args = ['market-events', action, '--input', str(self.events), '--event', 'notice', '--as-of', AS_OF]
        if action != 'lookup':
            args += ['--portfolio', str(self.portfolio), '--review', str(self.review)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main([*args, *map(str, extra)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def bytes(self):
        return {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}

    def test_lookup_and_preview_are_repeatable_and_preserve_every_input(self):
        before = self.bytes()
        for action, status in (('lookup', 'available'), ('preview', 'ready')):
            first = self.invoke(action)
            self.assertEqual(first, self.invoke(action))
            self.assertEqual((first[0], first[2]), (0, ''))
            self.assertEqual(json.loads(first[1])['status'], status)
            self.assertEqual(self.bytes(), before)

    def test_apply_requires_write_and_dry_run_suppresses_it(self):
        before = self.bytes()
        for flags in ((), ('--write', '--dry-run')):
            result = self.invoke('apply', *flags)
            self.assertEqual((result[0], result[2]), (0, ''))
            self.assertFalse(json.loads(result[1])['write'])
            self.assertEqual(self.bytes(), before)

    def test_write_appends_once_and_replay_does_not_rewrite_file(self):
        original = portfolio()
        result = self.invoke('apply', '--write')
        self.assertEqual((result[0], result[2]), (0, ''))
        self.assertTrue(json.loads(result[1])['write'])
        updated = json.loads(self.portfolio.read_text())
        self.assertEqual(len(updated['activities']), 1)
        self.assertEqual(updated['holdings'], original['holdings'])
        before = self.bytes()
        replay = self.invoke('apply', '--write')
        self.assertEqual(replay[0], 0)
        self.assertEqual(json.loads(replay[1])['status'], 'noop')
        self.assertFalse(json.loads(replay[1])['write'])
        self.assertEqual(self.bytes(), before)

    def test_unavailable_review_never_writes(self):
        value = split_review()
        value['post_quantity'] = 999
        self.review.write_text(json.dumps(value))
        before = self.bytes()
        code, out, err = self.invoke('apply', '--write')
        self.assertEqual(code, 1)
        self.assertTrue(err)
        self.assertEqual(self.bytes(), before)

    def test_duplicate_keys_in_review_are_rejected(self):
        self.review.write_text('{"reviewed":true,"reviewed":false}')
        before = self.bytes()
        code, out, err = self.invoke('apply', '--write')
        self.assertEqual((code, out), (1, ''))
        self.assertTrue(err)
        self.assertEqual(self.bytes(), before)

    def test_invalid_portfolio_is_rejected_before_write(self):
        value = portfolio()
        del value['profile']
        self.portfolio.write_text(json.dumps(value))
        before = self.bytes()
        code, out, err = self.invoke('apply', '--write')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('portfolio', err.lower())
        self.assertEqual(self.bytes(), before)

    def test_input_aliases_are_rejected_before_write(self):
        alias = self.root / 'alias.json'
        alias.symlink_to(self.portfolio)
        before = self.bytes()
        code, out, err = self.invoke('apply', '--write', '--review', alias)
        self.assertEqual((code, out), (1, ''))
        self.assertIn('overwrite', err.lower())
        self.assertEqual(self.bytes(), before)

    def test_atomic_writer_failure_leaves_original_portfolio(self):
        before = self.bytes()
        with patch('rikdom.storage.os.replace', side_effect=OSError('synthetic rename failure')):
            code, out, err = self.invoke('apply', '--write')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('synthetic rename failure', err)
        self.assertEqual(self.bytes(), before)
