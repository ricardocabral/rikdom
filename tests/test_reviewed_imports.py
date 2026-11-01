import copy
import unittest

from rikdom import reviewed_imports


def statement(amount=10):
    return {"provider": "synthetic", "holdings": [{"id": "h", "asset_type_id": "fund", "label": "Fund", "market_value": {"amount": amount, "currency": "USD"}}], "activities": [{"id": "a", "event_type": "buy", "effective_at": "2026-01-01T00:00:00Z", "holding_id": "h", "idempotency_key": "a"}]}


def apply(portfolio, raw, review=None):
    from rikdom.plugins import merge_holdings, merge_activities
    effective, report, state = reviewed_imports.prepare_reviewed_import(portfolio, raw, review)
    if not report["ok"]:
        return portfolio, report
    result = reviewed_imports.reviewed_merge_base(portfolio, state)
    result, _ = merge_holdings(result, effective)
    result, _ = merge_activities(result, effective)
    reviewed_imports.retain_reviewed_import(result, raw, state)
    return result, report


class ReviewedImportsTests(unittest.TestCase):
    def test_raw_reimport_keeps_review_and_exact_previous_effective_state(self):
        raw = statement()
        p, _ = apply({"holdings": [], "activities": []}, raw)
        review = {"version": 1, "decisions": [{"id": "review-a", "collection": "activities", "entity_id": "a", "changes": {"account_id": "account-a", "trade_at": "2025-12-31T00:00:00Z"}, "evidence": {"kind": "user_declaration", "source_ref": "review-note"}}, {"id": "review-h", "collection": "holdings", "entity_id": "h", "changes": {"account_id": "account-a"}, "evidence": {"kind": "user_declaration", "source_ref": "review-note"}}]}
        p, report = apply(p, raw, review)
        self.assertTrue(report["ok"])
        old = copy.deepcopy(p)
        p, report = apply(p, raw)
        self.assertTrue(report["ok"])
        self.assertEqual(p, old)
        self.assertEqual(p["activities"][0]["account_id"], "account-a")
        self.assertEqual(p["holdings"][0]["account_id"], "account-a")
        self.assertEqual(len(p["activities"]), 1)
        versions = p["extensions"]["rikdom_reviewed_imports"]["revisions"]
        self.assertEqual(versions[0]["source"], raw)
        self.assertNotIn("account_id", versions[0]["effective"]["activities"][0])
        self.assertEqual(versions[-1]["effective"]["activities"][0]["account_id"], "account-a")

    def test_changed_source_blocks_then_explicit_resolution_retains_history(self):
        p, _ = apply({"holdings": [], "activities": []}, statement())
        review = {"version": 1, "decisions": [{"id": "r", "collection": "holdings", "entity_id": "h", "changes": {"market_value": {"amount": 12}}, "evidence": {"kind": "user_declaration", "source_ref": "note"}}]}
        p, _ = apply(p, statement(), review)
        before = copy.deepcopy(p)
        _, report = apply(p, statement(11))
        self.assertFalse(report["ok"])
        self.assertEqual(p, before)
        conflict = report["conflicts"][0]
        self.assertEqual(conflict["decision_id"], "r")
        self.assertIn("valuation", conflict["affected_results"])
        resolution = {"version": 1, "resolutions": [{"decision_id": "r", "action": "accept_source", "reason": "confirmed revised statement", "source_revision": report["source_revision"]}]}
        p, report = apply(p, statement(11), resolution)
        self.assertTrue(report["ok"])
        self.assertEqual(p["holdings"][0]["market_value"]["amount"], 11)
        self.assertEqual(p["extensions"]["rikdom_reviewed_imports"]["revisions"][-2]["effective"]["holdings"][0]["market_value"]["amount"], 12)

    def test_ambiguous_source_identity_fails_without_mutation(self):
        p, _ = apply({"holdings": [], "activities": []}, statement())
        raw = statement()
        raw["activities"].append({**raw["activities"][0], "id": "other"})
        before = copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError, "[Aa]mbiguous"):
            apply(p, raw)
        self.assertEqual(p, before)

    def test_coverage_review_survives_raw_reimport_and_contradiction_blocks(self):
        raw = statement()
        raw['metadata'] = {'rikdom_import_diagnostics': {'version': 1, 'history_coverage': [{'scope': 'account-a', 'status': 'unknown', 'event_types': []}], 'unsupported_events': []}}
        review = {'version': 1, 'decisions': [{'id': 'coverage', 'collection': 'diagnostics', 'entity_id': 'statement', 'changes': {'history_coverage': [{'scope': 'account-a', 'status': 'complete', 'event_types': ['buy'], 'from': '2026-01-01', 'through': '2026-01-31', 'evidence': {'kind': 'user_declaration', 'source_ref': 'review-note'}}]}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'review-note'}}]}
        p, report = apply({'holdings': [], 'activities': []}, raw, review)
        self.assertTrue(report['ok'])
        effective, report, _ = reviewed_imports.prepare_reviewed_import(p, raw)
        self.assertEqual(effective['metadata']['rikdom_import_diagnostics']['history_coverage'][0]['status'], 'complete')
        changed = copy.deepcopy(raw)
        changed['metadata']['rikdom_import_diagnostics']['history_coverage'][0]['status'] = 'partial'
        _, report, _ = reviewed_imports.prepare_reviewed_import(p, changed)
        self.assertFalse(report['ok'])

    def test_invalid_reviews_cannot_change_identity_or_use_stale_resolution(self):
        raw = statement()
        p, _ = apply({'holdings': [], 'activities': []}, raw)
        review = {'version': 1, 'decisions': [{'id': 'bad', 'collection': 'activities', 'entity_id': 'a', 'changes': {'id': 'different'}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'note'}}]}
        with self.assertRaisesRegex(ValueError, 'identity'):
            apply(p, raw, review)
        with self.assertRaisesRegex(ValueError, 'source_revision'):
            apply(p, raw, {'version': 1, 'resolutions': [{'decision_id': 'missing', 'action': 'keep_review', 'reason': 'confirmed', 'source_revision': 'stale'}]})

    def test_cli_review_reimport_conflict_and_resolution_are_atomic(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from rikdom.cli import main
        from rikdom.storage import load_json, save_json
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / 'portfolio.json'
            p = load_json(root / 'tests/fixtures/portfolio.json')
            p.update(holdings=[], activities=[], extensions={})
            save_json(path, p)
            raw = statement()
            raw['generated_at'] = '2026-01-02T00:00:00Z'
            raw['activities'][0]['created_at'] = '2026-01-02T00:00:00Z'
            raw['activities'][0]['metadata'] = {'rikdom_source_identity': {'version': 1, 'scope': 'account-a', 'document_fingerprint': 'doc', 'signature': 'trade', 'occurrence': 0, 'kind': 'source'}}
            source = directory / 'statement.json'
            save_json(source, raw)
            review_path = directory / 'review.json'
            save_json(review_path, {'version': 1, 'decisions': [{'id': 'a-review', 'collection': 'activities', 'entity_id': 'a', 'changes': {'account_id': 'account-a', 'holding_id': 'h', 'trade_at': '2025-12-31T00:00:00Z'}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'review-note'}}]})
            args = ['import-statement', '--plugin', 'normalized-statement-json', '--input', str(source), '--data-dir', str(directory), '--plugins-dir', str(root / 'plugins'), '--import-log', str(directory / 'import.jsonl'), '--ingested-at', '2026-02-01T00:00:00Z']
            def run(*extra):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main([*args, *extra])
                return code, json.loads(out.getvalue()), err.getvalue()
            code, output, errors = run('--write', '--review-file', str(review_path))
            self.assertEqual(code, 0, errors)
            original = path.read_bytes()
            code, output, errors = run('--write')
            self.assertEqual(code, 0, errors)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(load_json(path)['activities'][0]['account_id'], 'account-a')
            raw['activities'][0]['effective_at'] = '2026-01-03T00:00:00Z'
            save_json(source, raw)
            log_before = (directory / 'import.jsonl').read_bytes()
            code, output, errors = run('--write')
            self.assertEqual(code, 1, errors)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual((directory / 'import.jsonl').read_bytes(), log_before)
            report = output['preflight']['review']
            self.assertFalse(report['ok'])
            save_json(review_path, {'version': 1, 'resolutions': [{'decision_id': 'a-review', 'action': 'keep_review', 'reason': 'confirmed revised date', 'source_revision': report['source_revision']}]})
            code, output, errors = run('--write', '--review-file', str(review_path))
            self.assertEqual(code, 0, errors)
            current = load_json(path)
            self.assertEqual(current['activities'][0]['effective_at'], raw['activities'][0]['effective_at'])
            self.assertEqual(current['activities'][0]['account_id'], 'account-a')
            self.assertEqual(current['extensions']['rikdom_reviewed_imports']['revisions'][0]['effective']['activities'][0]['effective_at'], '2026-01-01T00:00:00Z')

    def test_review_cannot_forge_source_identity_metadata(self):
        review = {'version': 1, 'decisions': [{'id': 'bad', 'collection': 'activities', 'entity_id': 'a', 'changes': {'metadata': {'rikdom_source_identity': {'kind': 'reviewed'}}}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'note'}}]}
        with self.assertRaisesRegex(ValueError, 'identity'):
            apply({'holdings': [], 'activities': []}, statement(), review)

    def test_reviewed_identity_cannot_be_bypassed_with_a_new_id_same_key(self):
        review = {'version': 1, 'decisions': [{'id': 'r', 'collection': 'activities', 'entity_id': 'a', 'changes': {'account_id': 'account-a'}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'note'}}]}
        p, _ = apply({'holdings': [], 'activities': []}, statement(), review)
        changed = statement()
        changed['activities'][0]['id'] = 'renamed'
        with self.assertRaisesRegex(ValueError, 'reviewed identity'):
            apply(p, changed)

    def test_accept_source_removes_review_only_holding_fields(self):
        raw = statement()
        review = {'version': 1, 'decisions': [{'id': 'r', 'collection': 'holdings', 'entity_id': 'h', 'changes': {'account_id': 'account-a', 'metadata': {'custom_review': 'note'}}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'note'}}]}
        p, _ = apply({'holdings': [], 'activities': []}, raw, review)
        _, report = apply(p, statement(11))
        resolution = {'version': 1, 'resolutions': [{'decision_id': 'r', 'action': 'accept_source', 'reason': 'confirmed', 'source_revision': report['source_revision']}]}
        p, _ = apply(p, statement(11), resolution)
        self.assertNotIn('account_id', p['holdings'][0])
        self.assertNotIn('custom_review', p['holdings'][0].get('metadata', {}))

    def test_real_cli_rejects_identity_bypasses_and_retires_holding_review(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from rikdom.cli import main
        from rikdom.storage import load_json, save_json
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / 'portfolio.json'
            p = load_json(root / 'tests/fixtures/portfolio.json')
            p.update(holdings=[], activities=[], extensions={})
            save_json(path, p)
            raw = statement()
            raw['generated_at'] = '2026-01-02T00:00:00Z'
            raw['activities'][0]['created_at'] = raw['generated_at']
            source, review_path = directory / 'statement.json', directory / 'review.json'
            save_json(source, raw)
            args = ['import-statement', '--plugin', 'normalized-statement-json', '--input', str(source), '--data-dir', str(directory), '--plugins-dir', str(root / 'plugins'), '--import-log', str(directory / 'import.jsonl'), '--ingested-at', '2026-02-01T00:00:00Z', '--write']
            def run(review=None):
                extra = []
                if review is not None:
                    save_json(review_path, review)
                    extra = ['--review-file', str(review_path)]
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main([*args, *extra])
                return code, out.getvalue(), err.getvalue()
            evidence = {'kind': 'user_declaration', 'source_ref': 'note'}
            before = path.read_bytes()
            bad_review = {'version': 1, 'decisions': [{'id': 'forge', 'collection': 'activities', 'entity_id': 'a', 'changes': {'metadata': {'rikdom_source_identity': {'kind': 'reviewed'}}}, 'evidence': evidence}]}
            code, _, errors = run(bad_review)
            self.assertEqual(code, 1)
            self.assertIn('identity', errors)
            self.assertEqual(path.read_bytes(), before)
            review = {'version': 1, 'decisions': [{'id': 'activity', 'collection': 'activities', 'entity_id': 'a', 'changes': {'account_id': 'account-a'}, 'evidence': evidence}, {'id': 'holding', 'collection': 'holdings', 'entity_id': 'h', 'changes': {'account_id': 'account-a', 'metadata': {'review_note': 'reviewed'}}, 'evidence': evidence}]}
            code, _, errors = run(review)
            self.assertEqual(code, 0, errors)
            before, log_before = path.read_bytes(), (directory / 'import.jsonl').read_bytes()
            raw['activities'][0]['id'] = 'renamed'
            save_json(source, raw)
            code, _, errors = run()
            self.assertEqual(code, 1)
            self.assertIn('reviewed identity', errors)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual((directory / 'import.jsonl').read_bytes(), log_before)
            raw['activities'][0]['id'] = 'a'
            raw['holdings'][0]['market_value']['amount'] = 11
            save_json(source, raw)
            code, output, errors = run()
            self.assertEqual(code, 1, errors)
            report = json.loads(output)['preflight']['review']
            code, _, errors = run({'version': 1, 'resolutions': [{'decision_id': 'holding', 'source_revision': report['source_revision'], 'action': 'accept_source', 'reason': 'confirmed source'}]})
            self.assertEqual(code, 0, errors)
            current = load_json(path)
            self.assertNotIn('account_id', current['holdings'][0])
            self.assertNotIn('review_note', current['holdings'][0].get('metadata', {}))
            self.assertEqual(current['activities'][0]['account_id'], 'account-a')

    def test_repeating_identical_review_document_is_idempotent(self):
        raw = statement()
        review = {'version': 1, 'decisions': [{'id': 'r', 'collection': 'activities', 'entity_id': 'a', 'changes': {'account_id': 'account-a'}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'note'}}]}
        p, _ = apply({'holdings': [], 'activities': []}, raw, review)
        repeated, report = apply(p, raw, review)
        self.assertTrue(report['ok'])
        self.assertEqual(repeated, p)

    def test_nonobject_metadata_cannot_remove_source_identity(self):
        review = {'version': 1, 'decisions': [{'id': 'r', 'collection': 'activities', 'entity_id': 'a', 'changes': {'metadata': None}, 'evidence': {'kind': 'user_declaration', 'source_ref': 'note'}}]}
        with self.assertRaisesRegex(ValueError, 'metadata'):
            apply({'holdings': [], 'activities': []}, statement(), review)
