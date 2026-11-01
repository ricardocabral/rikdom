"""Real CLI regressions from independent review of recurring source imports."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from rikdom.cli import main
from rikdom.storage import load_json, save_json
from tests.test_reviewed_imports import statement

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def import_workspace(raw, *, collapse_canonical=False):
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        portfolio_path = directory / 'portfolio.json'
        source_path = directory / 'statement.json'
        review_path = directory / 'review.json'
        log_path = directory / 'import.jsonl'
        seed = load_json(ROOT / 'tests/fixtures/portfolio.json')
        seed.update(holdings=[], activities=[], extensions={})
        save_json(portfolio_path, seed)
        raw = copy.deepcopy(raw)
        raw['generated_at'] = '2026-01-02T00:00:00Z'
        for activity in raw.get('activities', []):
            activity['created_at'] = raw['generated_at']
        save_json(source_path, raw)
        args = ['import-statement', '--plugin', 'normalized-statement-json', '--input', str(source_path), '--data-dir', str(directory), '--plugins-dir', str(ROOT / 'plugins'), '--import-log', str(log_path), '--ingested-at', '2026-02-01T00:00:00Z', '--write']
        if collapse_canonical:
            args.append('--collapse-canonical')

        def run(review=None):
            extra = []
            if review is not None:
                save_json(review_path, review)
                extra = ['--review-file', str(review_path)]
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = main([*args, *extra])
            return code, json.loads(output.getvalue()) if output.getvalue() else {}, errors.getvalue()

        yield raw, source_path, portfolio_path, log_path, run


def decision(collection, changes):
    return {'version': 1, 'decisions': [{'id': 'review', 'collection': collection, 'entity_id': 'h' if collection == 'holdings' else 'a', 'changes': changes, 'evidence': {'kind': 'user_declaration', 'source_ref': 'review-note'}}]}


class ReviewedImportReviewRegressions(unittest.TestCase):
    def test_canonical_collapse_cannot_overwrite_active_review_under_new_id(self):
        raw = statement()
        raw['holdings'][0].update(account_id='acct', metadata={'canonical_key': 'fund:x'})
        with import_workspace(raw, collapse_canonical=True) as (raw, source_path, path, log, run):
            code, _, errors = run(decision('holdings', {'market_value': {'amount': 12}}))
            self.assertEqual(code, 0, errors)
            before, log_before = path.read_bytes(), log.read_bytes()
            raw['holdings'][0]['id'] = 'renamed'
            raw['holdings'][0]['market_value']['amount'] = 99
            save_json(source_path, raw)
            code, _, errors = run()
            self.assertEqual(code, 1, 'Canonical collapse bypassed the active review')
            self.assertIn('reviewed identity', errors)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(log.read_bytes(), log_before)
            self.assertEqual(load_json(path)['holdings'][0]['market_value']['amount'], 12)

    def test_newly_accepted_source_fact_survives_omission_then_conflicting_refresh_blocks(self):
        with import_workspace(statement()) as (raw, source_path, path, log, run):
            code, _, errors = run(decision('activities', {'account_id': 'acct'}))
            self.assertEqual(code, 0, errors)
            raw['activities'][0]['money'] = {'amount': 100, 'currency': 'USD'}
            save_json(source_path, raw)
            code, _, errors = run()
            self.assertEqual(code, 0, errors)
            added = load_json(path)
            self.assertEqual(added['activities'][0]['money']['amount'], 100)
            old_revision = copy.deepcopy(added['extensions']['rikdom_reviewed_imports']['revisions'][0])
            raw['activities'][0].pop('money')
            save_json(source_path, raw)
            code, _, errors = run()
            self.assertEqual(code, 0, errors)
            before, log_before = path.read_bytes(), log.read_bytes()
            raw['activities'][0]['money'] = {'amount': 999, 'currency': 'USD'}
            save_json(source_path, raw)
            code, output, errors = run()
            self.assertEqual(code, 1, 'Accepted money100 was forgotten after omission')
            conflict = output['preflight']['review']['conflicts'][0]
            self.assertIn('money.amount', conflict['changed_source_fields'])
            self.assertEqual(conflict['previous_source']['money']['amount'], 100)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(log.read_bytes(), log_before)
            current = load_json(path)
            record = current['extensions']['rikdom_reviewed_imports']['decisions'][0]
            self.assertNotIn('money', record['source'])
            self.assertEqual(record['accepted_source']['money']['amount'], 100)
            self.assertEqual(record['version'], 1)
            self.assertEqual(current['extensions']['rikdom_reviewed_imports']['revisions'][0], old_revision)

    def test_omitted_source_money_and_evidence_remain_effective_for_reviewed_activity(self):
        raw = statement()
        raw['activities'][0].update(money={'amount': 100, 'currency': 'USD'}, metadata={'source_note': {'receipt': 'receipt-a'}})
        with import_workspace(raw) as (raw, source_path, path, _, run):
            code, _, errors = run(decision('activities', {'account_id': 'acct'}))
            self.assertEqual(code, 0, errors)
            raw['activities'][0].pop('money')
            raw['activities'][0].pop('metadata')
            save_json(source_path, raw)
            code, _, errors = run()
            self.assertEqual(code, 0, errors)
            activity = load_json(path)['activities'][0]
            self.assertEqual(activity.get('money'), {'amount': 100, 'currency': 'USD'})
            self.assertEqual(activity.get('metadata'), {'source_note': {'receipt': 'receipt-a'}})
            self.assertEqual(activity['account_id'], 'acct')

    def test_no_review_imports_keep_existing_collapse_and_source_replacement_behavior(self):
        raw = statement()
        raw['holdings'][0].update(account_id='acct', metadata={'canonical_key': 'fund:x'})
        raw['activities'][0]['money'] = {'amount': 100, 'currency': 'USD'}
        with import_workspace(raw, collapse_canonical=True) as (raw, source_path, path, _, run):
            self.assertEqual(run()[0], 0)
            raw['holdings'][0]['id'] = 'renamed'
            raw['holdings'][0]['market_value']['amount'] = 99
            raw['activities'][0].pop('money')
            save_json(source_path, raw)
            code, _, errors = run()
            self.assertEqual(code, 0, errors)
            current = load_json(path)
            self.assertEqual(len(current['holdings']), 1)
            self.assertEqual(current['holdings'][0]['id'], 'h')
            self.assertEqual(current['holdings'][0]['market_value']['amount'], 99)
            self.assertNotIn('money', current['activities'][0])
