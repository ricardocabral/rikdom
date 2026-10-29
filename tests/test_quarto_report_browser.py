"""Opt-in real-browser regression checks without a runtime browser dependency."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rikdom.income import build_income_report
from rikdom.income_planning import build_income_planning_report
from rikdom.plugin_engine.pipeline import run_output_pipeline


@unittest.skipUnless(
    os.environ.get("RIKDOM_PLAYWRIGHT_MODULE") and shutil.which("node"),
    "Set RIKDOM_PLAYWRIGHT_MODULE to an installed Playwright module for browser QA",
)
class OfflineReportBrowserTests(unittest.TestCase):
    def test_planning_reasons_localize_by_code_and_escape_unknown_or_legacy_text(self):
        portfolio = json.loads(Path('tests/fixtures/income_planning_portfolio.json').read_text())
        plan = json.loads(Path('tests/fixtures/income_plan.json').read_text())
        plan['announcements'][0]['payment_date'] = '2026-02-03'
        plan['cost_bases'][0]['coverage'] = 'partial'
        income = build_income_report(portfolio)
        income['planning'] = build_income_planning_report(portfolio, income, plan)
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / 'payload.json'
            payload.write_text(json.dumps({'sections': {'income': income}}))
            checked = subprocess.run(
                [shutil.which('node'), 'tests/browser/report_reasons.cjs', str(payload)],
                text=True, capture_output=True, timeout=120,
            )
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_generated_reports_work_after_relocation_without_remote_network(self):
        for fallback in (True, False):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                generated = root / "generated"
                environment = dict(os.environ)
                environment.pop("RIKDOM_DISABLE_QUARTO", None)
                if fallback:
                    environment["RIKDOM_DISABLE_QUARTO"] = "1"
                portfolio = json.loads(Path("tests/fixtures/portfolio.json").read_text())
                for index, holding in enumerate(portfolio["holdings"]):
                    holding["account_id"] = "qa-a" if index == 0 else "qa-b"
                portfolio["activities"].extend([
                    {"id": "qa-income-april", "event_type": "dividend", "status": "posted",
                     "effective_at": "2026-04-02T10:00:00-03:00", "account_id": "qa-a", "asset_type_id": "stock",
                     "money": {"amount": 12.5, "currency": "USD"}, "withholding_tax": {"amount": 2.5, "currency": "USD"}},
                    {"id": "qa-income-may", "event_type": "interest", "status": "posted",
                     "effective_at": "2026-05-02T10:00:00Z", "account_id": "qa-b", "asset_type_id": "fund",
                     "money": {"amount": 21, "currency": "BRL"}},
                    {"id": "qa-contribution", "event_type": "contribution", "status": "posted",
                     "effective_at": "2026-04-11T10:00:00Z", "account_id": "qa-a",
                     "money": {"amount": 30, "currency": "USD"}},
                ])
                plan = json.loads(Path("tests/fixtures/income_plan.json").read_text())
                for section in ("announcements", "estimates", "cost_bases"):
                    for row in plan[section]:
                        row["scope"] = {"account_id": "qa-a"}
                plan["announcements"][0]["money"]["amount"] = 12.5
                plan["announcements"][0]["payment_date"] = "2026-04-02"
                plan["estimates"][0]["payment_date"] = "2026-05-01"
                plan["estimates"][0]["assumptions"] = '<img src=x onerror="window.RIKDOM_XSS=true"> source assumption'
                plan["payment_links"][0]["activity_id"] = "qa-income-april"
                plan["cost_bases"][0]["money"]["amount"] = 250
                plan["cost_bases"][0]["period"] = {"start": "2026-04-01", "end": "2026-04-10"}
                unavailable = json.loads(json.dumps(plan["cost_bases"][0]))
                unavailable.update(id="cost-unknown", coverage="unknown")
                plan["cost_bases"].append(unavailable)
                portfolio["activities"][-3]["source_system"] = "sample-broker"
                portfolio["extensions"] = {"rikdom_income_plan": plan, "rikdom_report": {"locale": "pt"}}
                # Synthetic valid history for the intended four-point chart.
                # The repository sample has a non-leap Feb29; invalid-history
                # behavior is covered separately without rewriting source data.
                snapshots = Path("tests/fixtures/snapshots.jsonl").read_text().replace("2026-02-29", "2026-02-28")
                snapshots_path = root / "snapshots.jsonl"
                snapshots_path.write_text(snapshots)
                portfolio_path = root / "portfolio.json"
                portfolio_path.write_text(json.dumps(portfolio))
                with patch.dict(os.environ, environment, clear=True):
                    result = run_output_pipeline(
                        plugin_name="quarto-portfolio-report", plugins_dir="plugins",
                        portfolio_path=str(portfolio_path),
                        snapshots_path=str(snapshots_path),
                        output_dir=str(generated),
                    )
                if not fallback and result["warnings"]:
                    self.fail("Full Quarto rendering required for this opt-in check: " + str(result["warnings"]))
                # The temporary render workspace has already been deleted. Moving the
                # bundle also catches hidden absolute references to the output path.
                relocated = root / "relocated"
                generated.rename(relocated)
                checked = subprocess.run(
                    [shutil.which("node"), "tests/browser/report_offline.cjs", str(relocated),
                     "fallback" if fallback else "quarto"],
                    text=True, capture_output=True, timeout=120,
                )
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_source_calendar_dates_and_custom_asset_ids_are_stable(self):
        for fallback in (True, False):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                portfolio = {
                    'schema_version': '1.5.0', 'settings': {'base_currency': 'USD'},
                    'asset_type_catalog': [{'id': name, 'asset_class': 'stocks'} for name in ('stock', 'stock_options')],
                    'holdings': [{'id': name, 'label': name + ' source label', 'asset_type_id': name,
                                  'market_value': {'amount': 100, 'currency': 'USD'}} for name in ('stock', 'stock_options')],
                    'activities': [],
                }
                snapshots = [
                    {'timestamp': '2026-02-02T00:15:00+03:00', 'totals': {'portfolio_value_base': 300}},
                    {'timestamp': '2026-02-01T00:00:00Z', 'totals': {'portfolio_value_base': 200}},
                    {'timestamp': '2026-01-01T00:00:00Z', 'totals': {'portfolio_value_base': 100}},
                ]
                (root / 'portfolio.json').write_text(json.dumps(portfolio))
                (root / 'snapshots.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in snapshots))
                environment = dict(os.environ)
                environment.pop('RIKDOM_DISABLE_QUARTO', None)
                if fallback:
                    environment['RIKDOM_DISABLE_QUARTO'] = '1'
                with patch.dict(os.environ, environment, clear=True):
                    result = run_output_pipeline(
                        plugin_name='quarto-portfolio-report', plugins_dir='plugins',
                        portfolio_path=str(root / 'portfolio.json'), snapshots_path=str(root / 'snapshots.jsonl'),
                        output_dir=str(root / 'generated'),
                    )
                if not fallback:
                    self.assertEqual(result['warnings'], [])
                checked = subprocess.run(
                    [shutil.which('node'), 'tests/browser/report_calendar.cjs', str(root / 'generated'),
                     'fallback' if fallback else 'quarto'], text=True, capture_output=True, timeout=120,
                )
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
