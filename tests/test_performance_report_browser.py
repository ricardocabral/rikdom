"""Opt-in rendered behavior of the shared full/fallback performance panel."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('RIKDOM_PLAYWRIGHT_MODULE') and shutil.which('node'),
                     'Set RIKDOM_PLAYWRIGHT_MODULE for focused browser QA')
class PerformanceReportBrowserTests(unittest.TestCase):
    def test_returns_and_bridge_localize_escape_and_respect_date_window(self):
        payload = {'profile': {'base_currency': 'BRL'}, 'sections': {
            'current_valuation': {'base_currency': 'BRL', 'total_value_base': 176},
            'performance': {'base_currency': 'BRL', 'period_start': '2026-01-01T00:00:00Z',
                'period_end': '2027-01-01T00:00:00Z', 'twr_return_pct': 21,
                'twr_method': 'linked_subperiod', 'twr_return_basis': 'period',
                'mwr_pct': 25, 'mwr_return_basis': 'annualized_365_day',
                'growth_bridge': {'status': 'complete', 'base_currency': 'BRL', 'investment_result_base': 26},
                'profit_attribution': {'bridge': {'status': 'complete', 'investment_result_base': 26}},
                'warnings': ['<img src=x onerror="window.XSS=true">'],
                'treatment': {'income': 'Included in portfolio valuations'}},
            'income': {'events': []}, 'timeline': [],
        }}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'payload.json'
            path.write_text(json.dumps(payload))
            result = subprocess.run([shutil.which('node'), 'tests/browser/report_profit_attribution.cjs', str(path)],
                                    text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
