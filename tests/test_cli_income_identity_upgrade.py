"""Parser upgrades must not silently replace legacy income economics."""
from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.cli import main


class SourceIdentityUpgradeCliTests(unittest.TestCase):
    def import_activity(self, root, activity):
        source = root / 'statement.json'
        source.write_text(json.dumps({
            'provider': 'source-income-test', 'generated_at': '2026-04-04T00:00:00Z',
            'activities': [activity],
        }), encoding='utf-8')
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                'import-statement', '--plugin', 'normalized-statement-json',
                '--plugins-dir', 'plugins', '--portfolio', str(root / 'portfolio.json'),
                '--input', str(source), '--import-log', str(root / 'import_log.jsonl'),
                '--ingested-at', '2026-04-04T00:00:00Z', '--write',
            ])
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else {}, stderr.getvalue()

    @staticmethod
    def activity():
        return {
            'id': 'source-income-1', 'idempotency_key': 'source-income:key-1',
            'event_type': 'dividend', 'effective_at': '2026-04-01T00:00:00Z',
            'status': 'posted', 'money': {'amount': 10, 'currency': 'USD'},
            'fees': {'amount': 0, 'currency': 'USD'},
        }

    @staticmethod
    def add_source_identity(activity):
        activity['metadata'] = {
            'rikdom_source_identity': {
                'version': 1, 'kind': 'source', 'scope': 'opaque-account',
                'document_fingerprint': 'source-document', 'signature': 'source-economics',
                'occurrence': 0,
            },
            'rikdom_income': {'version': 1, 'amount_basis': 'unknown'},
        }

    def test_legacy_source_upgrade_conflict_blocks_before_canonical_writes(self):
        for match in ('id', 'idempotency_key', 'both'):
            for field, value in (
                ('money', {'amount': -10, 'currency': 'USD'}),
                ('event_type', 'tax_withheld'),
                ('fees', {'amount': -1, 'currency': 'USD'}),
            ):
                with self.subTest(match=match, field=field), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    portfolio, log = root / 'portfolio.json', root / 'import_log.jsonl'
                    portfolio.write_text(json.dumps({'holdings': [], 'activities': []}))
                    original = self.activity()
                    code, _, err = self.import_activity(root, original)
                    self.assertEqual(code, 0, err)
                    revised = copy.deepcopy(original)
                    self.add_source_identity(revised)
                    revised[field] = value
                    if match == 'id':
                        revised['idempotency_key'] = 'new-key'
                    elif match == 'idempotency_key':
                        revised['id'] = 'new-id'
                    before, log_before = portfolio.read_bytes(), log.read_bytes()
                    code, report, err = self.import_activity(root, revised)
                    self.assertEqual(code, 1, err)
                    self.assertFalse(report['write'])
                    self.assertIn('AMBIGUOUS_IMPORT_IDENTITY', [
                        issue['code'] for issue in report['preflight']['issues']])
                    self.assertEqual(portfolio.read_bytes(), before)
                    self.assertEqual(log.read_bytes(), log_before)

    def test_legacy_source_upgrade_can_add_optional_evidence_and_replay(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = root / 'portfolio.json'
            portfolio.write_text(json.dumps({'holdings': [], 'activities': []}))
            original = self.activity()
            code, _, err = self.import_activity(root, original)
            self.assertEqual(code, 0, err)
            revised = copy.deepcopy(original)
            self.add_source_identity(revised)
            revised['withholding_tax'] = {'amount': 0, 'currency': 'USD'}
            revised['settled_at'] = '2026-04-03T00:00:00Z'
            code, _, err = self.import_activity(root, revised)
            self.assertEqual(code, 0, err)
            stored = json.loads(portfolio.read_text())['activities']
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]['withholding_tax'], revised['withholding_tax'])
            before = portfolio.read_bytes()
            code, report, err = self.import_activity(root, revised)
            self.assertEqual(code, 0, err)
            self.assertEqual(report['activities']['skipped'], 1)
            self.assertEqual(portfolio.read_bytes(), before)
