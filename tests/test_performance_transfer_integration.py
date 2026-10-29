"""Internal-transfer invariants across report, calendar and CLI FX discovery."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from rikdom.cli import main
from rikdom.performance_periods import compute_calendar_performance
from rikdom.performance_report import recorded_contributions
from tests.test_internal_transfers import pair, snapshots
from tests.test_market_events import portfolio


class TransferIntegrationTests(unittest.TestCase):
    def test_portfolio_recorded_contributions_exclude_verified_internal_legs(self):
        rows = pair()
        external = {'id': 'external', 'event_type': 'contribution', 'status': 'posted',
                    'effective_at': '2026-01-20T00:00:00Z', 'money': {'amount': 5, 'currency': 'BRL'}}
        self.assertEqual([row['activity_id'] for row in recorded_contributions(rows + [external])], ['external'])

    def test_calendar_retains_full_ledger_conflict_evidence_before_slicing(self):
        rows = pair()
        conflict = copy.deepcopy(rows[0])
        conflict.update(event_type='contribution', effective_at='2026-02-10T00:00:00Z', metadata={})
        conflict['money']['amount'] = 5
        result = compute_calendar_performance(snapshots(), rows + [conflict], base_currency='BRL')
        january = result['monthly'][0]
        self.assertEqual(january['status'], 'unavailable')
        self.assertTrue(january['warnings'])

    def test_calendar_valid_pair_has_no_external_cashflow_and_preserves_provenance(self):
        result = compute_calendar_performance(snapshots(), pair(), base_currency='BRL')
        january = result['monthly'][0]
        self.assertEqual(january['status'], 'available')
        self.assertEqual(january['performance']['cashflow_count'], 0)
        self.assertEqual(january['performance']['internal_transfers']['status'], 'verified')
        self.assertEqual(january['performance']['twr_return_pct'], 10)

    def test_cli_scoped_foreign_pair_uses_available_cached_fx(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = portfolio()
            data['settings']['base_currency'] = 'BRL'
            data['holdings'] = []
            data['activities'] = pair()
            for row in data['activities']:
                row['money']['currency'] = 'USD'
            (root / 'portfolio.json').write_text(json.dumps(data))
            (root / 'snapshots.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in snapshots()))
            (root / 'fx.jsonl').write_text(json.dumps({'as_of_date': '2026-01-01', 'base_currency': 'BRL',
                'quote_currency': 'USD', 'rate_to_base': 5, 'source': 'manual:test'}) + '\n')
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['performance', '--portfolio', str(root / 'portfolio.json'),
                    '--snapshots', str(root / 'snapshots.jsonl'), '--fx-history', str(root / 'fx.jsonl'),
                    '--data-dir', str(root / 'data'), '--by', 'account'])
            self.assertEqual((code, err.getvalue()), (0, ''))
            result = json.loads(out.getvalue())
            self.assertEqual(result['cashflow_count'], 0)
            self.assertEqual([row['net_external_cashflow_base'] for row in result['by_account']], [-100, 100])
            self.assertTrue(all(row['twr_pct'] is not None for row in result['by_account']))
