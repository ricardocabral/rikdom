from __future__ import annotations

import csv
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.cli import main


class SchwabIdentityCliTests(unittest.TestCase):
    def write_csv(self, path, rows):
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                'record_type', 'account_number', 'date', 'action', 'symbol',
                'amount', 'currency', 'reference_id', 'fees',
            ])
            writer.writeheader()
            for fields in rows:
                writer.writerow(dict(record_type='transaction', account_number='A1',
                    date='04/01/2026', action='Cash Dividend', symbol='TAXF',
                    currency='USD', **fields))

    def import_file(self, root, source, plugin='charles-schwab'):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                'import-statement', '--plugin', plugin, '--plugins-dir', 'plugins',
                '--portfolio', str(root / 'portfolio.json'), '--input', str(source),
                '--import-log', str(root / 'import_log.jsonl'), '--write',
                '--ingested-at', '2026-04-02T00:00:00Z',
            ])
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else {}, stderr.getvalue()

    def test_separate_signed_anonymous_rows_block_without_changing_canonical_files(self):
        for first_amount in (10, -10):
            for legacy in (False, True):
                with self.subTest(first_amount=first_amount, legacy=legacy), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    portfolio, log = root / 'portfolio.json', root / 'import_log.jsonl'
                    portfolio.write_text(json.dumps({'schema_version': '2.0.0', 'holdings': [], 'activities': []}))
                    first, second = root / 'first.csv', root / 'second.csv'
                    self.write_csv(first, [{'amount': first_amount}])
                    self.write_csv(second, [{'amount': -first_amount}])
                    code, _, err = self.import_file(root, first)
                    self.assertEqual(code, 0, err)
                    if legacy:
                        stored = json.loads(portfolio.read_text())
                        stored['activities'][0]['metadata'].pop('rikdom_source_identity', None)
                        stored['activities'][0]['metadata'].pop('rikdom_income', None)
                        portfolio.write_text(json.dumps(stored))
                    before, log_before = portfolio.read_bytes(), log.read_bytes()
                    code, report, err = self.import_file(root, second)
                    self.assertEqual(code, 1, err)
                    self.assertFalse(report['write'])
                    self.assertIn('AMBIGUOUS_IMPORT_IDENTITY', [i['code'] for i in report['preflight']['issues']])
                    self.assertEqual(portfolio.read_bytes(), before)
                    self.assertEqual(log.read_bytes(), log_before)
                    code, _, err = self.import_file(root, first)
                    self.assertEqual(code, 0, err)
                    stored = json.loads(portfolio.read_text())
                    self.assertEqual(len(stored['activities']), 1)
                    self.assertEqual(stored['activities'][0]['money']['amount'], first_amount)
                    replay_before = portfolio.read_bytes()
                    code, replay, err = self.import_file(root, first)
                    self.assertEqual(code, 0, err)
                    self.assertEqual(replay['activities']['skipped'], 1)
                    self.assertEqual(portfolio.read_bytes(), replay_before)

    def test_confirmed_source_references_allow_distinct_signed_events_and_source_updates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = root / 'portfolio.json'
            portfolio.write_text(json.dumps({'holdings': [], 'activities': []}))
            positive, negative = root / 'positive.csv', root / 'negative.csv'
            self.write_csv(positive, [{'amount': 10, 'reference_id': 'confirmed-dividend'}])
            self.write_csv(negative, [{'amount': -10, 'reference_id': 'confirmed-reversal'}])
            for source in (positive, negative, positive, negative):
                code, _, err = self.import_file(root, source)
                self.assertEqual(code, 0, err)
            stored = json.loads(portfolio.read_text())
            self.assertEqual({a['id']: a['money']['amount'] for a in stored['activities']}, {
                'schwab-txn-a1-confirmed-dividend': 10, 'schwab-txn-a1-confirmed-reversal': -10,
            })
            self.write_csv(negative, [{'amount': -11, 'reference_id': 'confirmed-reversal'}])
            code, _, err = self.import_file(root, negative)
            self.assertEqual(code, 0, err)
            updated = json.loads(portfolio.read_text())['activities']
            self.assertEqual(len(updated), 2)
            self.assertEqual(next(a for a in updated if a['id'] == 'schwab-txn-a1-confirmed-reversal')['money']['amount'], -11)

    def test_row_reorder_replays_and_duplicate_rows_keep_existing_deduplication(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = root / 'portfolio.json'
            portfolio.write_text(json.dumps({'holdings': [], 'activities': []}))
            first, reordered = root / 'first.csv', root / 'renamed.csv'
            rows = [{'amount': 10}, {'amount': 5}]
            self.write_csv(first, [*rows, rows[0]])
            self.write_csv(reordered, [rows[1], rows[0], rows[0]])
            code, report, err = self.import_file(root, first)
            self.assertEqual(code, 0, err)
            self.assertEqual(report['activities']['inserted'], 2)
            before = portfolio.read_bytes()
            code, report, err = self.import_file(root, reordered)
            self.assertEqual(code, 0, err)
            self.assertEqual(report['activities']['skipped'], 2)
            self.assertEqual(portfolio.read_bytes(), before)

    def test_anonymous_replay_allows_new_metadata_and_optional_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio, source = root / 'portfolio.json', root / 'source.csv'
            portfolio.write_text(json.dumps({'holdings': [], 'activities': []}))
            self.write_csv(source, [{'amount': 10}])
            code, _, err = self.import_file(root, source)
            self.assertEqual(code, 0, err)
            stored = json.loads(portfolio.read_text())
            activity = stored['activities'][0]
            activity['metadata'].pop('rikdom_income')
            portfolio.write_text(json.dumps(stored))
            activity['metadata']['rikdom_income'] = {'version': 1, 'amount_basis': 'unknown'}
            activity.update(account_id='reviewed-account', holding_id='reviewed-holding',
                trade_at=activity['effective_at'], settled_at='2026-04-03T00:00:00Z')
            normalized = root / 'reviewed.json'
            normalized.write_text(json.dumps({'provider': 'charles-schwab',
                'generated_at': '2026-04-04T00:00:00Z', 'activities': [activity]}))
            code, _, err = self.import_file(root, normalized, 'normalized-statement-json')
            self.assertEqual(code, 0, err)
            enriched = json.loads(portfolio.read_text())['activities'][0]
            self.assertEqual(enriched['account_id'], 'reviewed-account')
            self.assertEqual(enriched['settled_at'], '2026-04-03T00:00:00Z')
            self.assertEqual(enriched['metadata']['rikdom_income']['amount_basis'], 'unknown')

    def test_anonymous_different_signature_cannot_replace_by_id_or_idempotency_key(self):
        for match in ('id', 'idempotency_key', 'both'):
            with self.subTest(match=match), TemporaryDirectory() as tmp:
                root = Path(tmp)
                portfolio, source = root / 'portfolio.json', root / 'source.csv'
                portfolio.write_text(json.dumps({'holdings': [], 'activities': []}))
                self.write_csv(source, [{'amount': 10}])
                code, _, err = self.import_file(root, source)
                self.assertEqual(code, 0, err)
                activity = json.loads(portfolio.read_text())['activities'][0]
                activity['metadata']['rikdom_source_identity'] = {
                    'version': 1, 'scope': 'opaque-account', 'document_fingerprint': 'other-doc',
                    'signature': 'different-economics', 'occurrence': 0, 'kind': 'anonymous',
                }
                activity['money']['amount'] = -10
                if match != 'both':
                    other_key = 'idempotency_key' if match == 'id' else 'id'
                    activity[other_key] = 'another-identity'
                normalized = root / 'conflicting.json'
                normalized.write_text(json.dumps({'provider': 'charles-schwab',
                    'generated_at': '2026-04-04T00:00:00Z', 'activities': [activity]}))
                before, log_before = portfolio.read_bytes(), (root / 'import_log.jsonl').read_bytes()
                code, report, err = self.import_file(root, normalized, 'normalized-statement-json')
                self.assertEqual(code, 1, err)
                self.assertIn('AMBIGUOUS_IMPORT_IDENTITY', [i['code'] for i in report['preflight']['issues']])
                self.assertEqual(portfolio.read_bytes(), before)
                self.assertEqual((root / 'import_log.jsonl').read_bytes(), log_before)
