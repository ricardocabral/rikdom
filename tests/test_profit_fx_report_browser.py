"""Offline presentation must disclose every reconciled FX component."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('RIKDOM_PLAYWRIGHT_MODULE') and shutil.which('node'),
                     'Set RIKDOM_PLAYWRIGHT_MODULE for focused browser QA')
class ProfitFxReportBrowserTests(unittest.TestCase):
    def test_price_fx_cash_and_conversion_breakdown_in_both_report_modes(self):
        payload = {'profile': {'base_currency': 'BRL'}, 'sections': {
            'performance': {'base_currency': 'BRL', 'period_start': '2026-01-01T00:00:00Z',
                'period_end': '2026-02-01T00:00:00Z', 'twr_method': 'modified_dietz',
                'twr_return_basis': 'period', 'mwr_return_basis': 'annualized_365_day',
                'profit_attribution': {'diagnostics': [], 'decomposition': {
                    'status': 'complete', 'realized_gain_base': 12,
                    'unrealized_change_base': 15, 'net_income_base': 8,
                    'standalone_fees_base': 2, 'standalone_taxes_base': 1,
                    'cash_fx_gain_base': 5, 'fx_conversion_result_base': 3,
                    'realized_price_gain_base': 7, 'realized_fx_gain_base': 5,
                    'unrealized_price_change_base': 6, 'unrealized_fx_change_base': 9,
                    'explained_result_base': 40, 'reconciliation_difference_base': 0}}},
            'income': {'events': []}, 'timeline': []}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'payload.json'
            path.write_text(json.dumps(payload))
            run = subprocess.run([shutil.which('node'), 'tests/browser/report_profit_fx.cjs', str(path)],
                                 text=True, capture_output=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
