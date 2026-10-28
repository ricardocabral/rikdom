"""Behavioral payload contracts for local, honest report scopes."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('report_plugin', Path('plugins/quarto-portfolio-report/plugin.py'))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class ReportScopeTests(unittest.TestCase):
    def test_scopes_use_asserted_dimensions_and_preserve_unknown_history(self):
        portfolio = {
            'schema_version': '1.5.0', 'settings': {'base_currency': 'USD'},
            'extensions': {'rikdom_report': {'locale': 'pt'}},
            'asset_type_catalog': [{'id': 'stock', 'asset_class': 'stocks'}, {'id': 'fund', 'asset_class': 'funds'}],
            'holdings': [
                {'id': 'h1', 'account_id': 'a', 'asset_type_id': 'stock', 'market_value': {'amount': 100, 'currency': 'USD'}},
                {'id': 'h2', 'account_id': 'b', 'asset_type_id': 'fund', 'market_value': {'amount': 40, 'currency': 'USD'}},
            ],
            'activities': [
                {'id': 'income-a', 'event_type': 'dividend', 'status': 'posted', 'effective_at': '2026-04-01T10:00:00-03:00',
                 'account_id': 'a', 'asset_type_id': 'stock', 'money': {'amount': 5, 'currency': 'USD'}, 'withholding_tax': {'amount': 1, 'currency': 'USD'}},
                {'id': 'unattributed', 'event_type': 'interest', 'status': 'posted', 'effective_at': '2026-05-01T10:00:00Z',
                 'money': {'amount': 2, 'currency': 'EUR'}},
                {'id': 'deposit-a', 'event_type': 'contribution', 'status': 'posted', 'effective_at': '2026-04-02T10:00:00Z',
                 'account_id': 'a', 'money': {'amount': 20, 'currency': 'USD'}},
            ],
        }
        snapshots = [{'timestamp': '2026-04-01T00:00:00Z', 'totals': {'portfolio_value_base': 999}}]
        before = copy.deepcopy(portfolio)
        payload = plugin._build_report_payload(portfolio, snapshots)
        self.assertEqual(payload['profile'].get('language'), 'pt')
        self.assertEqual(portfolio, before)
        self.assertEqual(len(payload['sections']['income']['events']), 2)
        scopes = {(v['dimension'], v['value']): v['sections'] for v in payload.get('report_views', [])}
        self.assertEqual(len(scopes), 6)  # two accounts, two asset types, two currencies
        account = scopes[('account_id', 'a')]
        self.assertEqual(account['current_valuation']['total_value_base'], 100)
        self.assertEqual([r['activity_id'] for r in account['income']['events']], ['income-a'])
        self.assertEqual([r['activity_id'] for r in account['contributions']], ['deposit-a'])
        self.assertEqual(account['timeline'], [])
        self.assertEqual(account['historical_status'], 'unavailable_for_scope')
        self.assertAlmostEqual(payload['sections']['presentation']['largest_holding_share'], 100 / 140)
        self.assertEqual(account['presentation']['largest_holding_share'], 1)
        self.assertEqual(account['presentation']['holding_shares']['h1'], 1)
        self.assertEqual(account['presentation']['allocation_shares']['Asset type breakdown'], {'stock': 1})
        self.assertEqual(scopes[('currency', 'EUR')]['current_valuation']['total_value_base'], 0)
        self.assertEqual(scopes[('currency', 'EUR')]['income']['events'][0]['activity_id'], 'unattributed')
