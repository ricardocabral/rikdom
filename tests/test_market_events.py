"""Synthetic announcements cannot establish payments or historical positions."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from rikdom.market_events import (
    apply_market_event, load_market_events, parse_market_events, preview_market_event,
)
from rikdom.activities import effective_activities
from rikdom.validate import validate_portfolio


AS_OF = '2026-02-01T00:00:00Z'
IDENTITY = {'namespace': 'SYNTHETIC-US', 'id': 'DEMO', 'currency': 'USD'}


def event(kind='split'):
    revision = {'id': 'r1', 'effective_at': '2026-01-10T00:00:00Z',
                'retrieved_at': '2026-01-02T00:00:00Z', 'source': 'manual:synthetic-notice',
                'supersedes': None}
    revision.update({'ratio': 2} if kind == 'split' else {
        'per_unit': {'amount': 0.5, 'currency': 'USD'},
        'record_at': None, 'payment_at': '2026-01-20T00:00:00Z'})
    return {'id': 'notice', 'kind': kind, 'instrument': copy.deepcopy(IDENTITY),
            'adjustment_basis': 'unadjusted',
            'coverage': {'start': '2026-01-01T00:00:00Z', 'end': '2026-02-28T23:59:59Z'},
            'license': {'name': 'CC0-1.0 synthetic only', 'uri': 'https://example.invalid/synthetic'},
            'revisions': [revision]}


def document(kind='split'):
    return {'contract_version': '1.0', 'events': [event(kind)]}


def portfolio():
    return {'schema_version': '2.0.0', 'schema_uri': 'https://example.org/rikdom/schema/portfolio.schema.json',
            'profile': {'portfolio_id': 'p', 'owner_kind': 'person', 'display_name': 'Synthetic'},
            'settings': {'base_currency': 'USD'},
            'asset_type_catalog': [{'id': 'stock', 'asset_class': 'stocks'}],
            'holdings': [{'id': 'h1', 'label': 'Demo', 'asset_type_id': 'stock',
                          'account_id': 'account', 'instrument': copy.deepcopy(IDENTITY),
                          'quantity': 20, 'market_value': {'amount': 200, 'currency': 'USD'}}],
            'activities': []}


def split_review(**changes):
    return {'contract_version': '1.0', 'reviewed': True, 'revision_id': 'r1',
            'holding_id': 'h1', 'account_id': 'account', 'source': 'manual:position-statement',
            'quantity_basis': 'unadjusted', 'pre_quantity': 10, 'post_quantity': 20, **changes}


def payment():
    return {'id': 'observed', 'idempotency_key': 'broker:observed', 'event_type': 'dividend',
            'status': 'posted', 'effective_at': '2026-01-20T00:00:00Z',
            'holding_id': 'h1', 'account_id': 'account', 'instrument': copy.deepcopy(IDENTITY),
            'money': {'amount': 4, 'currency': 'USD'}, 'source_ref': 'statement:line-4',
            'withholding_tax': {'amount': 1, 'currency': 'USD'},
            'metadata': {'keep': 'original'}, 'extensions': {'keep': {'value': 7}}}


def distribution_review(**changes):
    return {'contract_version': '1.0', 'reviewed': True, 'revision_id': 'r1',
            'observed_activity_id': 'observed', 'source': 'statement:reviewed-correction',
            'money': {'amount': 5, 'currency': 'USD'}, 'amount_basis': 'gross', **changes}


class MarketEventsTests(unittest.TestCase):
    def preview(self, p=None, payload=None, review=None, **kwargs):
        return preview_market_event(portfolio() if p is None else p,
                                    parse_market_events(document() if payload is None else payload),
                                    event_id='notice', as_of=AS_OF, review=review, **kwargs)

    def test_announcements_require_review_and_never_create_income(self):
        p = portfolio()
        original = copy.deepcopy(p)
        for kind in ('split', 'distribution'):
            report = self.preview(p=p, payload=document(kind))
            self.assertEqual((report['status'], report['reason'], report['activities']),
                             ('unavailable', 'review_required', []))
        self.assertEqual(p, original)

    def test_revision_cutoff_preserves_zero_and_missing_distinction(self):
        payload = document('distribution')
        root = payload['events'][0]['revisions'][0]
        root['per_unit']['amount'] = 0
        revised = {**copy.deepcopy(root), 'id': 'r2', 'retrieved_at': '2026-01-11T00:00:00Z',
                   'supersedes': 'r1', 'per_unit': None}
        payload['events'][0]['revisions'].insert(0, revised)
        store = parse_market_events(payload)
        early = store.lookup('notice', as_of=AS_OF, retrieved_before='2026-01-02T00:00:00Z')
        self.assertEqual(early['revision']['per_unit']['amount'], 0)
        latest = store.lookup('notice', as_of=AS_OF)
        self.assertIsNone(latest['revision']['per_unit'])
        self.assertEqual([r['id'] for r in latest['superseded']], ['r1'])
        latest['revision']['per_unit'] = {'amount': 999, 'currency': 'USD'}
        payload['events'][0]['revisions'].clear()
        self.assertIsNone(store.lookup('notice', as_of=AS_OF)['revision']['per_unit'])

    def test_unknown_coverage_future_and_knowledge_cutoff_are_unavailable(self):
        store = parse_market_events(document())
        for event_id, when, cutoff, reason in [
            ('absent', AS_OF, None, 'unknown_event'),
            ('notice', '2026-03-01T00:00:00Z', None, 'outside_declared_coverage'),
            ('notice', '2026-01-05T00:00:00Z', None, 'event_not_effective'),
            ('notice', AS_OF, '2026-01-01T00:00:00Z', 'no_known_revision'),
        ]:
            with self.subTest(reason=reason):
                result = store.lookup(event_id, as_of=when, retrieved_before=cutoff)
                self.assertEqual((result['status'], result['reason']), ('missing', reason))

    def test_rejects_unknown_fields_versions_and_malformed_numbers(self):
        cases = []
        p = document()
        p['contract_version'] = '2.0'
        cases.append(p)
        p = document()
        p['events'][0]['extra'] = True
        cases.append(p)
        p = document()
        p['events'][0]['instrument']['currency'] = 'usd'
        cases.append(p)
        p = document()
        p['events'][0]['license'] = {}
        cases.append(p)
        p = document()
        p['events'][0]['coverage']['end'] = '2025-01-01T00:00:00Z'
        cases.append(p)
        p = document()
        p['events'][0]['revisions'][0]['effective_at'] = '2026-02-30T00:00:00Z'
        cases.append(p)
        for value in (True, 0, -1, float('nan'), float('inf'), 10**400, '2'):
            p = document()
            p['events'][0]['revisions'][0]['ratio'] = value
            cases.append(p)
        for value in (True, -1, float('nan'), float('inf'), '2'):
            p = document('distribution')
            p['events'][0]['revisions'][0]['per_unit']['amount'] = value
            cases.append(p)
        for p in cases:
            with self.subTest(payload=p), self.assertRaises(ValueError):
                parse_market_events(p)

    def test_rejects_duplicate_ids_missing_references_cycles_and_forks(self):
        cases = []
        p = document()
        p['events'].append(copy.deepcopy(p['events'][0]))
        cases.append(p)
        p = document()
        p['events'][0]['revisions'] *= 2
        cases.append(p)
        for previous in ('absent', 'r1'):
            p = document()
            p['events'][0]['revisions'][0]['supersedes'] = previous
            cases.append(p)
        p = document()
        root = p['events'][0]['revisions'][0]
        p['events'][0]['revisions'] += [
            {**root, 'id': 'r2', 'supersedes': 'r1', 'retrieved_at': '2026-01-03T00:00:00Z'},
            {**root, 'id': 'r3', 'supersedes': 'r1', 'retrieved_at': '2026-01-04T00:00:00Z'}]
        cases.append(p)
        p = document()
        p['events'][0]['revisions'].append({**root, 'id': 'other'})
        cases.append(p)
        for p in cases:
            with self.subTest(payload=p), self.assertRaises(ValueError):
                parse_market_events(p)

    def test_in_memory_contract_rejects_json_coercions(self):
        cases = []
        payload = document()
        payload['events'] = tuple(payload['events'])
        cases.append(payload)
        payload = document()
        payload['events'][0]['license'][7] = 'not a JSON key'
        cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_market_events(payload)

    def test_file_loader_rejects_duplicate_keys_and_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.json'
            for text in ('{"contract_version":"1.0","events":[],"events":[]}',
                         '{"contract_version":"1.0","events":[],"bad":NaN}'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_market_events(path)

    def test_split_preview_is_deterministic_and_read_only(self):
        p = portfolio()
        before = copy.deepcopy(p)
        first = self.preview(p=p, review=split_review())
        self.assertEqual(first, self.preview(p=p, review=split_review()))
        self.assertEqual(first['status'], 'ready')
        action = first['activities'][0]
        self.assertEqual(action['corporate_action'], {'kind': 'split', 'exchange_ratio': 2,
                         'legs': [{'holding_id': 'h1', 'quantity_delta': 10}]})
        self.assertNotIn('money', action)
        self.assertEqual(p, before)

    def test_split_apply_appends_without_rewriting_positions_prices_or_lots(self):
        p = portfolio()
        p['tax_lots'] = []
        p['extensions'] = {'prices': [{'value': 10, 'adjustment': 'split_adjusted'}]}
        before = copy.deepcopy(p)
        candidate, result = apply_market_event(p, parse_market_events(document()),
                            event_id='notice', as_of=AS_OF, review=split_review())
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(len(candidate['activities']), 1)
        self.assertEqual(candidate['holdings'], before['holdings'])
        self.assertEqual(candidate['extensions'], before['extensions'])
        self.assertEqual(candidate['tax_lots'], [])
        self.assertEqual(p, before)
        self.assertEqual(validate_portfolio(candidate), [])
        again, replay = apply_market_event(candidate, parse_market_events(document()),
                            event_id='notice', as_of=AS_OF, review=split_review())
        self.assertEqual(replay['status'], 'noop')
        self.assertEqual(again, candidate)

    def test_reverse_split_signed_delta(self):
        payload = document()
        payload['events'][0]['revisions'][0]['ratio'] = 0.1
        result = self.preview(payload=payload, review=split_review(pre_quantity=100, post_quantity=10))
        self.assertEqual(result['activities'][0]['corporate_action']['kind'], 'reverse_split')
        self.assertEqual(result['activities'][0]['corporate_action']['legs'][0]['quantity_delta'], -90)

    def test_incomplete_positions_wrong_identity_or_account_cannot_apply(self):
        cases = []
        p = portfolio()
        p['holdings'] = []
        cases.append((p, split_review(), 'holding_not_found'))
        p = portfolio()
        p['holdings'][0]['instrument']['namespace'] = 'OTHER'
        cases.append((p, split_review(), 'instrument_mismatch'))
        p = portfolio()
        p['holdings'][0].pop('account_id')
        cases.append((p, split_review(), 'account_mismatch'))
        cases.append((portfolio(), split_review(post_quantity=21), 'split_quantity_mismatch'))
        cases.append((portfolio(), split_review(pre_quantity=0, post_quantity=0), 'no_position_evidence'))
        for p, review, reason in cases:
            with self.subTest(reason=reason):
                result = self.preview(p=p, review=review)
                self.assertEqual((result['status'], result['reason']), ('unavailable', reason))
                with self.assertRaises(ValueError):
                    apply_market_event(p, parse_market_events(document()), event_id='notice', as_of=AS_OF, review=review)

    def test_adjusted_unit_or_quote_basis_rejected(self):
        for basis in ('split_adjusted', 'total_return_adjusted'):
            payload = document()
            payload['events'][0]['adjustment_basis'] = basis
            self.assertEqual(self.preview(payload=payload, review=split_review())['reason'], 'unsupported_adjustment_basis')
            self.assertEqual(self.preview(review=split_review(quantity_basis=basis))['reason'], 'unsupported_quantity_basis')
        with self.assertRaises(ValueError):
            self.preview(review=split_review(price={'value': 100, 'adjustment': 'split_adjusted'}))

    def test_stale_review_schema_and_unreviewed_evidence_cannot_apply(self):
        self.assertEqual(self.preview(review=split_review(revision_id='old'))['reason'], 'review_revision_mismatch')
        self.assertEqual(self.preview(review=split_review(reviewed=False))['reason'], 'review_required')
        p = portfolio()
        p['schema_version'] = '1.7.0'
        self.assertEqual(self.preview(p=p, review=split_review())['reason'], 'schema_upgrade_required')

    def test_provider_split_revision_cannot_duplicate_already_applied_action(self):
        store = parse_market_events(document())
        candidate, _ = apply_market_event(portfolio(), store, event_id='notice', as_of=AS_OF, review=split_review())
        revised = document()
        root = revised['events'][0]['revisions'][0]
        revised['events'][0]['revisions'].append({**root, 'id': 'r2', 'supersedes': 'r1', 'retrieved_at': '2026-01-12T00:00:00Z', 'ratio': 3})
        result = self.preview(p=candidate, payload=revised, review=split_review(revision_id='r2', post_quantity=30))
        self.assertEqual(result['reason'], 'split_revision_requires_manual_correction')
        self.assertEqual(len(candidate['activities']), 1)

    def test_distribution_correction_preserves_original_and_projects_one_payment(self):
        p = portfolio()
        p['activities'] = [payment()]
        before = copy.deepcopy(p)
        candidate, result = apply_market_event(p, parse_market_events(document('distribution')),
                            event_id='notice', as_of=AS_OF, review=distribution_review())
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(candidate['activities'][0], before['activities'][0])
        self.assertEqual(len(candidate['activities']), 2)
        selected = effective_activities(candidate['activities'])
        self.assertEqual([a['money']['amount'] for a in selected], [5])
        self.assertEqual(selected[0]['withholding_tax']['amount'], 1)
        self.assertEqual(selected[0]['extensions']['keep'], {'value': 7})
        self.assertEqual(selected[0]['metadata']['keep'], 'original')
        self.assertEqual(p, before)
        self.assertEqual(validate_portfolio(candidate), [])
        again, replay = apply_market_event(candidate, parse_market_events(document('distribution')),
                            event_id='notice', as_of=AS_OF, review=distribution_review())
        self.assertEqual(replay['status'], 'noop')
        self.assertEqual(again, candidate)

    def test_distribution_provider_revision_corrects_current_leaf_idempotently(self):
        p = portfolio()
        p['activities'] = [payment()]
        first, _ = apply_market_event(p, parse_market_events(document('distribution')),
                    event_id='notice', as_of=AS_OF, review=distribution_review())
        revised = document('distribution')
        root = revised['events'][0]['revisions'][0]
        revised['events'][0]['revisions'].append({**root, 'id': 'r2', 'supersedes': 'r1', 'retrieved_at': '2026-01-22T00:00:00Z'})
        review = distribution_review(revision_id='r2', money={'amount': 6, 'currency': 'USD'})
        second, _ = apply_market_event(first, parse_market_events(revised), event_id='notice', as_of=AS_OF, review=review)
        self.assertEqual([a['money']['amount'] for a in effective_activities(second['activities'])], [6])
        self.assertEqual(second['activities'][:2], first['activities'])
        again, result = apply_market_event(second, parse_market_events(revised), event_id='notice', as_of=AS_OF, review=review)
        self.assertEqual((len(again['activities']), result['status']), (3, 'noop'))
        old_replay, result = apply_market_event(second, parse_market_events(document('distribution')), event_id='notice', as_of=AS_OF, review=distribution_review())
        self.assertEqual(old_replay, second)
        self.assertEqual(result['status'], 'noop')

    def test_distribution_cannot_apply_unseen_ancestor_or_unrelated_revision_after_newer_review(self):
        payload = document('distribution')
        root = payload['events'][0]['revisions'][0]
        payload['events'][0]['revisions'].append({**root, 'id': 'r2', 'supersedes': 'r1',
            'retrieved_at': '2026-01-22T00:00:00Z'})
        p = portfolio()
        p['activities'] = [payment()]
        store = parse_market_events(payload)
        newer, _ = apply_market_event(p, store, event_id='notice', as_of=AS_OF,
            review=distribution_review(revision_id='r2', money={'amount': 6, 'currency': 'USD'}))
        unrelated = document('distribution')
        unrelated['events'][0]['revisions'][0].update(id='r3', retrieved_at='2026-01-23T00:00:00Z')
        for candidate in (newer, self.with_unmarked_payment_correction(newer)):
            before = copy.deepcopy(candidate)
            cases = [
                (store, distribution_review(), '2026-01-21T00:00:00Z'),
                (parse_market_events(document('distribution')), distribution_review(), None),
                (parse_market_events(unrelated), distribution_review(revision_id='r3'), None),
            ]
            for events, review, cutoff in cases:
                with self.subTest(revision=review['revision_id'], cutoff=cutoff,
                                  activities=len(candidate['activities'])):
                    preview = preview_market_event(candidate, events, event_id='notice', as_of=AS_OF,
                        review=review, retrieved_before=cutoff)
                    self.assertEqual((preview['status'], preview['reason'], preview['activities']),
                                     ('unavailable', 'stale_or_unrelated_revision', []))
                    with self.assertRaisesRegex(ValueError, 'stale_or_unrelated_revision'):
                        apply_market_event(candidate, events, event_id='notice', as_of=AS_OF,
                            review=review, retrieved_before=cutoff)
                    self.assertEqual(candidate, before)
            self.assertEqual([a['money']['amount'] for a in effective_activities(candidate['activities'])],
                             [6] if len(candidate['activities']) == 2 else [7])

    @staticmethod
    def with_unmarked_payment_correction(portfolio):
        candidate = copy.deepcopy(portfolio)
        leaf = copy.deepcopy(candidate['activities'][-1])
        leaf.update(id='manual-leaf', idempotency_key='manual-leaf', money={'amount': 7, 'currency': 'USD'})
        leaf['extensions'].pop('rikdom_market_event')
        leaf['extensions']['rikdom_correction'] = {'version': 1,
            'supersedes_activity_id': candidate['activities'][-1]['id'], 'reason': 'Reviewed manually'}
        candidate['activities'].append(leaf)
        return candidate

    def test_distribution_announcements_cannot_invent_entitlement_or_payment(self):
        payload = document('distribution')
        p = portfolio()
        self.assertEqual(self.preview(p=p, payload=payload, review=distribution_review())['reason'], 'observed_payment_not_found')
        p['activities'] = [payment()]
        p['activities'][0]['status'] = 'pending'
        self.assertEqual(self.preview(p=p, payload=payload, review=distribution_review())['reason'], 'observed_payment_not_posted')
        p['activities'][0] = payment()
        p['holdings'] = []
        self.assertEqual(self.preview(p=p, payload=payload, review=distribution_review())['reason'], 'holding_not_found')
        self.assertEqual(p['activities'][0]['money']['amount'], 4)

    def test_distribution_zero_is_observed_correction_without_tax_inference(self):
        p = portfolio()
        p['activities'] = [payment()]
        p['activities'][0].pop('withholding_tax')
        candidate, _ = apply_market_event(p, parse_market_events(document('distribution')),
                    event_id='notice', as_of=AS_OF, review=distribution_review(money={'amount': 0, 'currency': 'USD'}, amount_basis='unknown'))
        current = effective_activities(candidate['activities'])[0]
        self.assertEqual(current['money']['amount'], 0)
        self.assertNotIn('withholding_tax', current)
        self.assertEqual(current['metadata']['rikdom_income']['amount_basis'], 'unknown')

    def test_distribution_refuses_conflicting_review_or_tax_lot_dependencies(self):
        p = portfolio()
        p['activities'] = [payment()]
        candidate, _ = apply_market_event(p, parse_market_events(document('distribution')),
                    event_id='notice', as_of=AS_OF, review=distribution_review())
        result = self.preview(p=candidate, payload=document('distribution'), review=distribution_review(money={'amount': 99, 'currency': 'USD'}))
        self.assertEqual(result['reason'], 'applied_review_conflict')
        p['tax_lots'] = [{'id': 'lot', 'acquisition_activity_id': 'observed'}]
        result = self.preview(p=p, payload=document('distribution'), review=distribution_review())
        self.assertEqual(result['reason'], 'dependent_activity_review_required')

    def test_duplicate_portfolio_references_fail_closed(self):
        for field in ('holdings', 'activities'):
            p = portfolio()
            p['activities'] = [payment()]
            p[field].append(copy.deepcopy(p[field][0]))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.preview(p=p, review=split_review())

    def test_tiny_quantity_cannot_pass_as_a_zero_post_split_position(self):
        result = self.preview(review=split_review(pre_quantity=1e-20, post_quantity=0))
        self.assertEqual(result['reason'], 'split_quantity_mismatch')

    def test_existing_split_leg_cannot_be_added_again(self):
        p = portfolio()
        p['activities'] = [{'id': 'broker-split', 'event_type': 'split', 'status': 'posted',
            'effective_at': '2026-01-10T00:00:00Z',
            'corporate_action': {'kind': 'split', 'exchange_ratio': 2,
                                 'legs': [{'holding_id': 'h1', 'quantity_delta': 10}]}}]
        self.assertEqual(self.preview(p=p, review=split_review())['reason'], 'existing_split_requires_review')

    def test_distribution_current_correction_cannot_move_to_another_instrument(self):
        p = portfolio()
        p['activities'] = [payment()]
        changed = copy.deepcopy(payment())
        changed.update(id='manual-correction', idempotency_key='manual-correction')
        changed['instrument']['id'] = 'OTHER'
        changed['extensions']['rikdom_correction'] = {
            'version': 1, 'supersedes_activity_id': 'observed', 'reason': 'Manual identity correction'}
        p['activities'].append(changed)
        result = self.preview(p=p, payload=document('distribution'), review=distribution_review())
        self.assertEqual(result['reason'], 'observed_payment_identity_changed')
        self.assertEqual(len(p['activities']), 2)

    def test_same_revision_id_with_changed_source_evidence_cannot_be_reapplied(self):
        p = portfolio()
        p['activities'] = [payment()]
        candidate, _ = apply_market_event(p, parse_market_events(document('distribution')),
                    event_id='notice', as_of=AS_OF, review=distribution_review())
        altered = document('distribution')
        altered['events'][0]['revisions'][0]['source'] = 'different:notice'
        result = self.preview(p=candidate, payload=altered, review=distribution_review())
        self.assertEqual(result['reason'], 'applied_revision_conflict')

    def test_revised_future_date_never_falls_back_to_obsolete_announcement(self):
        payload = document()
        root = payload['events'][0]['revisions'][0]
        payload['events'][0]['revisions'].append({**root, 'id': 'r2', 'supersedes': 'r1',
            'retrieved_at': '2026-01-12T00:00:00Z', 'effective_at': '2026-02-10T00:00:00Z'})
        result = self.preview(payload=payload, review=split_review(revision_id='r2'))
        self.assertEqual(result['reason'], 'event_not_effective')
        self.assertEqual(result['selection']['revision']['id'], 'r2')

    def test_review_nonfinite_boolean_and_cross_currency_amounts_rejected_without_mutation(self):
        p = portfolio()
        p['activities'] = [payment()]
        before = copy.deepcopy(p)
        reviews = [distribution_review(money={'amount': value, 'currency': 'USD'})
                   for value in (True, float('inf'), float('nan'), -1)]
        reviews.append(distribution_review(money={'amount': 4, 'currency': 'BRL'}))
        for review in reviews:
            with self.subTest(review=review), self.assertRaises(ValueError):
                self.preview(p=p, payload=document('distribution'), review=review)
        self.assertEqual(p, before)

    def test_sample_reviewed_actions_replay_without_touching_source_files(self):
        root = Path(__file__).resolve().parents[1] / 'data-sample' / 'market-events'
        paths = [root / name for name in ('portfolio.json', 'us.json', 'split-review.json', 'distribution-review.json')]
        before = {path: path.read_bytes() for path in paths}
        p = json.loads(before[paths[0]])
        store = load_market_events(root / 'us.json')
        split = json.loads(before[root / 'split-review.json'])
        corrected = json.loads(before[root / 'distribution-review.json'])
        candidate, _ = apply_market_event(p, store, event_id='synthetic-us-split', as_of=AS_OF, review=split)
        candidate, _ = apply_market_event(candidate, store, event_id='synthetic-us-distribution', as_of=AS_OF, review=corrected)
        self.assertEqual(len(candidate['activities']), 3)
        self.assertEqual([a['money']['amount'] for a in effective_activities(candidate['activities'])
                          if a['event_type'] == 'dividend'], [5])
        self.assertEqual(validate_portfolio(candidate), [])
        for path in paths:
            self.assertEqual(path.read_bytes(), before[path])

    def test_synthetic_regional_files_load_and_preview_without_mutation(self):
        root = Path(__file__).resolve().parents[1] / 'data-sample' / 'market-events'
        for region in ('br', 'us', 'jp'):
            path = root / f'{region}.json'
            before = path.read_bytes()
            store = load_market_events(path)
            result = store.lookup(f'synthetic-{region}-distribution', as_of=AS_OF)
            self.assertEqual(result['status'], 'available')
            self.assertIn('synthetic', result['event']['license']['name'].lower())
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
