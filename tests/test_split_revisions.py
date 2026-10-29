"""Reviewed split revisions replace one action and retain immutable evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rikdom.activities import effective_activities, validate_activity_import
from rikdom.market_events import apply_market_event, parse_market_events, preview_market_event
from rikdom.plugins import merge_activities
from rikdom.validate import validate_portfolio
from tests.test_market_events import AS_OF, document, portfolio, split_review


def revisions(*ratios):
    payload = document()
    root = payload['events'][0]['revisions'][0]
    payload['events'][0]['revisions'] = [
        {**root, 'id': f'r{i}', 'ratio': ratio,
         'supersedes': f'r{i-1}' if i > 1 else None,
         'retrieved_at': f'2026-01-{i+1:02d}T00:00:00Z'}
        for i, ratio in enumerate(ratios, 1)]
    return payload


def review(rid='r2', ratio=3, **changes):
    return split_review(**{'contract_version': '1.1', 'revision_id': rid, 'post_quantity': 10 * ratio,
                           'effective_at': '2026-01-10T00:00:00Z',
                           'reviewed_at': '2026-01-20T00:00:00Z', **changes})


def apply(p, payload, reviewed, **kwargs):
    return apply_market_event(p, parse_market_events(payload), event_id='notice',
                              as_of=AS_OF, review=reviewed, **kwargs)


class SplitRevisionTests(unittest.TestCase):
    def initial(self, payload=None):
        return apply(portfolio(), payload or revisions(2), split_review())[0]

    def preview(self, p, payload, reviewed, **kwargs):
        return preview_market_event(p, parse_market_events(payload), event_id='notice',
                                    as_of=AS_OF, review=reviewed, **kwargs)

    def test_ratio_revision_replaces_full_split_preserving_originals(self):
        p = self.initial()
        before = copy.deepcopy(p)
        candidate, report = apply(p, revisions(2, 3), review())
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(p, before)
        self.assertEqual(candidate['activities'][0], before['activities'][0])
        self.assertEqual(candidate['holdings'], before['holdings'])
        self.assertEqual(len(candidate['activities']), 2)
        effective = effective_activities(candidate['activities'])
        self.assertEqual(len(effective), 1)
        self.assertEqual(effective[0]['corporate_action']['exchange_ratio'], 3)
        self.assertEqual(effective[0]['corporate_action']['legs'][0]['quantity_delta'], 20)
        link = candidate['activities'][1]['extensions']['rikdom_correction']
        self.assertEqual(link['supersedes_activity_id'], p['activities'][0]['id'])

    def test_reverse_split_revision_and_three_vintage_old_replays(self):
        first = apply(
            portfolio(), revisions(0.5), split_review(post_quantity=5))[0]
        second, _ = apply(first, revisions(0.5, 0.25), review(ratio=0.25))
        third, _ = apply(second, revisions(0.5, 0.25, 0.1), review('r3', 0.1))
        self.assertEqual(len(third['activities']), 3)
        action = effective_activities(third['activities'])[0]['corporate_action']
        self.assertEqual((action['kind'], action['exchange_ratio'], action['legs'][0]['quantity_delta']),
                         ('reverse_split', 0.1, -9))
        for payload, reviewed in [(revisions(0.5), split_review(post_quantity=5)),
                                  (revisions(0.5, 0.25), review(ratio=0.25)),
                                  (revisions(0.5, 0.25, 0.1), review('r3', 0.1))]:
            again, report = apply(third, payload, reviewed)
            self.assertEqual((report['status'], again), ('noop', third))

    def test_r2_first_rejects_unseen_ancestor_and_unrelated_or_changed_source(self):
        p, _ = apply(portfolio(), revisions(2, 3), review())
        self.assertEqual(self.preview(p, revisions(2), split_review())['reason'], 'stale_or_unrelated_revision')
        p = self.initial()
        for field, value in [('ratio', 2.1), ('source', 'different-source'),
                             ('effective_at', '2026-01-09T00:00:00Z')]:
            payload = revisions(2, 3)
            payload['events'][0]['revisions'][0][field] = value
            self.assertEqual(self.preview(p, payload, review())['reason'], 'applied_revision_conflict')
        payload = revisions(2, 3)
        payload['events'][0]['revisions'][0]['id'] = 'other'
        payload['events'][0]['revisions'][1]['supersedes'] = 'other'
        self.assertEqual(self.preview(p, payload, review())['reason'], 'stale_or_unrelated_revision')

    def test_effective_date_revision_requires_matching_review_and_query_time(self):
        p = self.initial()
        payload = revisions(2, 3)
        payload['events'][0]['revisions'][1]['effective_at'] = '2026-01-15T00:00:00Z'
        self.assertEqual(self.preview(p, payload, review())['reason'], 'review_effective_date_mismatch')
        reviewed = review(effective_at='2026-01-15T00:00:00Z')
        candidate, _ = apply(p, payload, reviewed)
        self.assertEqual(effective_activities(candidate['activities'])[0]['effective_at'], reviewed['effective_at'])
        for timestamp in ('2026-01-14T00:00:00Z', '2026-02-02T00:00:00Z'):
            self.assertEqual(self.preview(p, payload, review(effective_at=reviewed['effective_at'], reviewed_at=timestamp))['reason'],
                             'review_time_inconsistent')
        payload['events'][0]['revisions'][1]['effective_at'] = '2026-02-10T00:00:00Z'
        self.assertEqual(self.preview(p, payload, review())['reason'], 'event_not_effective')

    def test_revision_requires_explicit_dates_and_unchanged_raw_pre_quantity(self):
        p = self.initial()
        self.assertEqual(self.preview(p, revisions(2, 3), split_review(revision_id='r2', post_quantity=30))['reason'],
                         'split_revision_review_required')
        changed = review()
        changed.update(pre_quantity=20, post_quantity=60)
        self.assertEqual(self.preview(p, revisions(2, 3), changed)['reason'], 'split_pre_quantity_changed')
        for basis in ('split_adjusted', 'total_return_adjusted'):
            self.assertEqual(self.preview(p, revisions(2, 3), review(quantity_basis=basis))['reason'], 'unsupported_quantity_basis')

    def test_holding_lots_and_unsupported_downstream_actions_block_revisions(self):
        p = self.initial()
        for lot in ({'id': 'l', 'holding_id': 'h1'},
                    {'id': 'l', 'acquisition_activity_id': p['activities'][0]['id']}):
            candidate = copy.deepcopy(p)
            candidate['tax_lots'] = [lot]
            self.assertEqual(self.preview(candidate, revisions(2, 3), review())['reason'], 'dependent_activity_review_required')
        candidate = copy.deepcopy(p)
        candidate['activities'].append({'id': 'later', 'event_type': 'corporate_action',
            'effective_at': '2026-01-25T00:00:00Z', 'holding_id': 'h1',
            'corporate_action': {'kind': 'merger', 'legs': [{'holding_id': 'h1', 'quantity_delta': 0}]}})
        self.assertEqual(self.preview(candidate, revisions(2, 3), review())['reason'], 'dependent_activity_review_required')

    def test_narrow_import_proof_rejects_manual_and_tampered_corrections(self):
        p = self.initial()
        proposal = self.preview(p, revisions(2, 3), review())['activities'][0]
        validate_activity_import(p, {'activities': [proposal]})
        for mutate in (
            lambda a: a['corporate_action'].update(exchange_ratio=4),
            lambda a: a.update(effective_at='2026-01-09T00:00:00Z'),
            lambda a: a.update(source_ref='forged'),
            lambda a: a['extensions'].pop('rikdom_market_event'),
            lambda a: a['extensions']['rikdom_market_event']['review'].update(reviewed=False),
        ):
            bad = copy.deepcopy(proposal)
            mutate(bad)
            with self.assertRaises(ValueError):
                merge_activities(copy.deepcopy(p), {'activities': [bad]})
        lot = {'id': 'l', 'holding_id': 'h1'}
        with self.assertRaises(ValueError):
            validate_activity_import(p, {'activities': [proposal], 'tax_lots': [lot]})

    def test_two_accounts_and_holdings_keep_independent_revision_chains(self):
        p = portfolio()
        other = copy.deepcopy(p['holdings'][0])
        other.update(id='h2', account_id='other')
        p['holdings'].append(other)
        p, _ = apply(p, revisions(2), split_review())
        p, _ = apply(p, revisions(2), split_review(holding_id='h2', account_id='other'))
        p, _ = apply(p, revisions(2, 3), review())
        rows = effective_activities(p['activities'])
        self.assertEqual({a['holding_id']: a['corporate_action']['exchange_ratio'] for a in rows}, {'h1': 3, 'h2': 2})

    def test_replay_checks_retained_ancestor_source_and_historical_review_dates(self):
        p, _ = apply(self.initial(), revisions(2, 3), review())
        changed = revisions(2, 3)
        changed['events'][0]['revisions'][0]['source'] = 'rewritten'
        self.assertEqual(self.preview(p, changed, review())['reason'], 'applied_revision_conflict')
        p['activities'][-1]['extensions']['rikdom_market_event']['review']['effective_at'] = '2026-01-09T00:00:00Z'
        self.assertEqual(self.preview(p, revisions(2, 3, 4), review('r3', 4))['reason'], 'applied_revision_conflict')

    def test_proof_cannot_change_scope_add_money_legs_or_hide_ancestor_lot(self):
        p = self.initial()
        second, _ = apply(p, revisions(2, 3), review())
        proposal = self.preview(second, revisions(2, 3, 4), review('r3', 4))['activities'][0]
        for mutate in (
            lambda a: a.update(holding_id='h2'),
            lambda a: a.update(account_id='other'),
            lambda a: a.update(money={'amount': 100, 'currency': 'USD'}),
            lambda a: a['corporate_action']['legs'].append({'holding_id': 'h2', 'quantity_delta': 1}),
            lambda a: a['extensions']['rikdom_correction'].update(supersedes_activity_id=p['activities'][0]['id']),
        ):
            bad = copy.deepcopy(proposal)
            mutate(bad)
            with self.subTest(activity=bad), self.assertRaises(ValueError):
                validate_activity_import(second, {'activities': [bad]})
        second['tax_lots'] = [{'id': 'ancestor-lot', 'acquisition_activity_id': p['activities'][0]['id']}]
        with self.assertRaises(ValueError):
            validate_activity_import(second, {'activities': [proposal]})

    def test_same_notice_is_scoped_to_namespaced_holdings_and_detects_identity_changes(self):
        p = self.initial()
        payload = revisions(2, 3)
        payload['events'][0]['instrument']['namespace'] = 'OTHER'
        changed = copy.deepcopy(p)
        changed['holdings'][0]['instrument']['namespace'] = 'OTHER'
        self.assertEqual(self.preview(changed, payload, review())['reason'], 'applied_revision_conflict')
        other = copy.deepcopy(p['holdings'][0])
        other.update(id='h2')
        other['instrument']['namespace'] = 'OTHER'
        p['holdings'].append(other)
        p, _ = apply(p, payload, review(holding_id='h2'))
        self.assertEqual(len(effective_activities(p['activities'])), 2)

    def test_cutoff_cannot_downgrade_and_old_unseen_ancestor_remains_blocked(self):
        p, _ = apply(portfolio(), revisions(2, 3), review())
        report = self.preview(p, revisions(2, 3), split_review(), retrieved_before='2026-01-02T00:00:00Z')
        self.assertEqual(report['reason'], 'stale_or_unrelated_revision')
        candidate, _ = apply(p, revisions(2, 3, 4), review('r3', 4))
        self.assertEqual(len(candidate['activities']), 2)
        self.assertEqual(effective_activities(candidate['activities'])[0]['corporate_action']['exchange_ratio'], 4)

    def test_real_cli_applies_revised_split_and_old_replays_preserve_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, source, reviewed = [root / name for name in ('portfolio.json', 'events.json', 'review.json')]
            target.write_text(json.dumps(portfolio()))

            def invoke(payload, evidence):
                source.write_text(json.dumps(payload))
                reviewed.write_text(json.dumps(evidence))
                result = subprocess.run([sys.executable, '-m', 'rikdom', 'market-events', 'apply',
                    '--input', str(source), '--review', str(reviewed), '--portfolio', str(target),
                    '--event', 'notice', '--as-of', AS_OF, '--write'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            self.assertTrue(invoke(revisions(2), split_review())['write'])
            first = json.loads(target.read_text())['activities'][0]
            self.assertTrue(invoke(revisions(2, 3), review())['write'])
            stored = json.loads(target.read_text())
            self.assertEqual(stored['activities'][0], first)
            self.assertEqual(len(stored['activities']), 2)
            self.assertEqual(len(effective_activities(stored['activities'])), 1)
            original_bytes, original_mtime = target.read_bytes(), target.stat().st_mtime_ns
            for payload, evidence in ((revisions(2, 3), review()), (revisions(2), split_review())):
                replay = invoke(payload, evidence)
                self.assertEqual((replay['status'], replay['write']), ('noop', False))
                self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), (original_bytes, original_mtime))

    def test_legacy_initial_split_marker_can_be_revised_from_exact_retained_source(self):
        for initial_ratio, rid in ((2, 'r1'), (3, 'r2')):
            payload = revisions(2) if rid == 'r1' else revisions(2, 3)
            p, _ = apply(portfolio(), payload, split_review(revision_id=rid, post_quantity=10 * initial_ratio))
            marker = p['activities'][0]['extensions']['rikdom_market_event']
            marker.pop('source_chain')
            marker.pop('query')
            original = copy.deepcopy(p['activities'][0])
            candidate, _ = apply(p, revisions(2, 3, 4), review('r3', 4))
            self.assertEqual(candidate['activities'][0], original)
            self.assertEqual(len(effective_activities(candidate['activities'])), 1)

    def test_unstructured_later_split_requires_dependency_review(self):
        p = self.initial()
        p['activities'].append({'id': 'later', 'event_type': 'split',
            'effective_at': '2026-01-25T00:00:00Z', 'holding_id': 'h1', 'account_id': 'account'})
        self.assertEqual(self.preview(p, revisions(2, 3), review())['reason'], 'dependent_activity_review_required')

    def test_review_proof_rejects_boolean_versions_and_quantity_deltas(self):
        p = self.initial()
        proposal = self.preview(p, revisions(2, 1), review(ratio=1))['activities'][0]
        for mutate in (
            lambda a: a['extensions']['rikdom_market_event'].update(version=True),
            lambda a: a['corporate_action'].update(exchange_ratio=True),
            lambda a: a['corporate_action']['legs'][0].update(quantity_delta=False),
        ):
            bad = copy.deepcopy(proposal)
            mutate(bad)
            with self.subTest(activity=bad), self.assertRaises(ValueError):
                validate_activity_import(p, {'activities': [bad]})

    def test_schema_valid_downstream_dependencies_require_review(self):
        later = {'id': 'later', 'event_type': 'buy', 'status': 'posted',
                 'effective_at': '2026-01-25T00:00:00Z', 'holding_id': 'h1',
                 'account_id': 'account', 'quantity': 1,
                 'money': {'amount': 10, 'currency': 'USD'}}
        for extra in (
            {'event_type': 'merger'},
            {'cost_basis_adjustment': {'amount': 5, 'currency': 'USD'}},
            {'cost_basis_adjustment': {'amount': 0, 'currency': 'USD'}},
            {'event_type': 'sell', 'tax_lot_ids': ['external-lot']},
        ):
            p = self.initial()
            proposal = self.preview(p, revisions(2, 3), review())['activities'][0]
            p['activities'].append({**copy.deepcopy(later), **extra})
            with self.subTest(extra=extra):
                self.assertEqual(validate_portfolio(p), [])
                self.assertEqual(self.preview(p, revisions(2, 3), review())['reason'],
                                 'dependent_activity_review_required')
                with self.assertRaises(ValueError):
                    validate_activity_import(p, {'activities': [proposal]})

    def test_dependency_audit_follows_downstream_correction_lineage_across_scope_changes(self):
        for risk in ({'cost_basis_adjustment': {'amount': 0, 'currency': 'USD'}},
                     {'tax_lot_ids': ['external-lot']}):
            p = self.initial()
            other = copy.deepcopy(p['holdings'][0])
            other['id'] = 'h2'
            p['holdings'].append(other)
            original = {'id': 'later', 'event_type': 'buy', 'status': 'posted',
                        'effective_at': '2026-01-25T00:00:00Z', 'holding_id': 'h1',
                        'account_id': 'account', 'quantity': 1,
                        'money': {'amount': 10, 'currency': 'USD'}}
            corrected = {**copy.deepcopy(original), 'id': 'later-corrected', 'holding_id': 'h2',
                         'idempotency_key': 'later-corrected', **risk,
                         'extensions': {'rikdom_correction': {'version': 1,
                             'supersedes_activity_id': 'later', 'reason': 'Reviewed changed allocation'}}}
            p['activities'].extend([original, corrected])
            with self.subTest(risk=risk):
                self.assertEqual(validate_portfolio(p), [])
                self.assertEqual(self.preview(p, revisions(2, 3), review())['reason'],
                                 'dependent_activity_review_required')
            # Moving the dependency to an ancestor must not hide it either.
            original.update(risk)
            for field in risk:
                corrected.pop(field)
            self.assertEqual(validate_portfolio(p), [])
            self.assertEqual(self.preview(p, revisions(2, 3), review())['reason'],
                             'dependent_activity_review_required')

    def test_leg_scoped_dependencies_block_but_plain_downstream_trades_remain_recalculable(self):
        p = self.initial()
        for aid, kind in (('buy', 'buy'), ('sell', 'sell')):
            p['activities'].append({'id': aid, 'event_type': kind, 'status': 'posted',
                'effective_at': '2026-01-25T00:00:00Z', 'holding_id': 'h1',
                'account_id': 'account', 'quantity': 1, 'money': {'amount': 10, 'currency': 'USD'}})
        self.assertEqual(validate_portfolio(p), [])
        candidate, report = apply(p, revisions(2, 3), review())
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(len(effective_activities(candidate['activities'])), 3)
        other = copy.deepcopy(p['holdings'][0])
        other['id'] = 'h2'
        p['holdings'].append(other)
        p['tax_lots'] = [{'id': 'other-lot', 'holding_id': 'h2',
                         'acquired_at': '2026-01-01T00:00:00Z', 'quantity': 1,
                         'cost_basis': {'amount': 10, 'currency': 'USD'}}]
        p['activities'].append({'id': 'legs', 'event_type': 'merger', 'status': 'posted',
            'effective_at': '2026-01-25T00:00:00Z', 'holding_id': 'h2', 'account_id': 'account',
            'corporate_action': {'kind': 'merger', 'legs': [{'holding_id': 'h1', 'quantity_delta': 0,
                'tax_lot_ids': ['other-lot'], 'cost_basis_delta': {'amount': 0, 'currency': 'USD'}}]}})
        self.assertEqual(validate_portfolio(p), [])
        self.assertEqual(self.preview(p, revisions(2, 3), review())['reason'],
                         'dependent_activity_review_required')

    def test_malformed_dates_and_nonfinite_review_values_raise(self):
        p = self.initial()
        for changes in ({'effective_at': '2026-01-10'}, {'reviewed_at': 'tomorrow'},
                        {'post_quantity': float('inf')}, {'pre_quantity': float('nan')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.preview(p, revisions(2, 3), review(**changes))


if __name__ == '__main__':
    unittest.main()
