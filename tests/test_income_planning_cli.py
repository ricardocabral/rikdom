"""Local planning must stay separate from received money and canonical writes."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rikdom.cli import main
from rikdom.income import build_income_report
from rikdom.instrument_performance import compute_instrument_performance


def source():
    return {'kind': 'manual', 'reference': 'Reviewed sample evidence', 'as_of': '2026-01-01'}


def sample_portfolio():
    return {'schema_version': '2.0.0', 'holdings': [], 'activities': [{
        'id': 'payment-1', 'event_type': 'dividend', 'status': 'posted',
        'effective_at': '2026-02-01T00:00:00Z', 'holding_id': 'holding-1',
        'money': {'amount': 50, 'currency': 'USD'},
        'withholding_tax': {'amount': 0, 'currency': 'USD'},
        'provenance': {'source_system': 'sample-broker'},
    }]}


def sample_plan():
    scope = {'holding_id': 'holding-1'}
    return {'version': 1, 'announcements': [{
        'id': 'ann-1', 'revision': 1, 'status': 'announced', 'source': source(),
        'scope': scope, 'income_type': 'dividend', 'payment_date': '2026-02-01',
        'money': {'amount': 50, 'currency': 'USD'}, 'amount_basis': 'gross', 'amount_kind': 'total',
    }], 'estimates': [{
        'id': 'scenario-1', 'scenario': 'Illustration only', 'source': source(),
        'scope': scope, 'income_type': 'dividend', 'payment_date': '2026-03-01',
        'money': {'amount': 999, 'currency': 'USD'}, 'amount_basis': 'gross',
        'assumptions': 'Illustrative fixed payment; no statement evidence.',
    }], 'payment_links': [{
        'announcement_id': 'ann-1', 'activity_id': 'payment-1', 'source': source(),
    }], 'cost_bases': [{
        'id': 'cost-1', 'scope': scope, 'source': source(), 'method': 'declared_constant_cost',
        'period': {'start': '2026-01-01', 'end': '2026-12-31'},
        'money': {'amount': 1000, 'currency': 'USD'}, 'amount_basis': 'gross',
        'coverage': 'complete', 'income_source_system': 'sample-broker',
    }]}


class IncomePlanningCliTests(unittest.TestCase):
    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(['income', *map(str, args)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_optional_plan_preserves_received_output_and_does_not_mutate_inputs(self):
        portfolio, plan = sample_portfolio(), sample_plan()
        before = copy.deepcopy((portfolio, plan))
        received = build_income_report(portfolio)
        result = build_income_report(portfolio, income_plan=plan)
        self.assertEqual({key: value for key, value in result.items() if key not in ('planning', 'limitations')},
                         {key: value for key, value in received.items() if key != 'limitations'})
        self.assertTrue(any('separate' in item for item in result['limitations']))
        self.assertEqual(result['monthly'][0]['gross']['total'], 50)
        self.assertEqual(result['planning']['reconciliation'][0]['status'], 'matched')
        self.assertEqual(result['planning']['yield_on_cost'][0]['ratio'], .05)
        self.assertEqual((portfolio, plan), before)

    def test_local_json_markdown_and_source_files_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical, plan_path, output = root / 'portfolio.json', root / 'plan.json', root / 'out'
            canonical.write_text(json.dumps(sample_portfolio()))
            plan_path.write_text(json.dumps(sample_plan()))
            before = canonical.read_bytes(), plan_path.read_bytes()
            code, stdout, stderr = self.run_cli('--portfolio', canonical, '--income-plan', plan_path,
                                               '--out-dir', output)
            self.assertEqual((code, stderr), (0, ''))
            report = json.loads(stdout)
            self.assertEqual(json.loads((output / 'income.json').read_text()), report)
            markdown = (output / 'income.md').read_text()
            for text in ('Announced income', 'Scenario estimates', 'Payment reconciliation',
                         'Yield on cost', 'ann-1', 'matched', 'declared_constant_cost', '5.00%'):
                self.assertIn(text, markdown)
            self.assertEqual(report['monthly'][0]['gross']['total'], 50)
            self.assertEqual((canonical.read_bytes(), plan_path.read_bytes()), before)

    def test_embedded_plan_and_explicit_override(self):
        portfolio = sample_portfolio()
        portfolio['extensions'] = {'rikdom_income_plan': sample_plan()}
        result = build_income_report(portfolio)
        self.assertEqual(result['planning']['yield_on_cost'][0]['ratio'], .05)
        portfolio['extensions']['rikdom_income_plan'] = {'version': 99}
        result = build_income_report(portfolio, income_plan={'version': 1})
        self.assertEqual(result['planning']['announced'], [])
        with self.assertRaises(ValueError):
            build_income_report(portfolio)

    def test_invalid_explicit_or_embedded_plans_fail_before_artifact_writes(self):
        for plan in ({'version': 99}, None, [], {'version': True}):
            for embedded in (False, True):
                with self.subTest(plan=plan, embedded=embedded), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    canonical, plan_path, output = root / 'portfolio.json', root / 'plan.json', root / 'out'
                    portfolio = sample_portfolio()
                    args = ['--portfolio', canonical, '--out-dir', output]
                    if embedded:
                        portfolio['extensions'] = {'rikdom_income_plan': plan}
                    else:
                        plan_path.write_text(json.dumps(plan))
                        args.extend(['--income-plan', plan_path])
                    canonical.write_text(json.dumps(portfolio))
                    before = canonical.read_bytes()
                    code, stdout, stderr = self.run_cli(*args)
                    self.assertEqual(code, 1)
                    self.assertEqual(stdout, '')
                    self.assertTrue(stderr)
                    self.assertFalse(output.exists())
                    self.assertEqual(canonical.read_bytes(), before)

    def test_artifacts_cannot_overwrite_the_plan_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical, plan_path = root / 'portfolio.json', root / 'income.json'
            canonical.write_text(json.dumps(sample_portfolio()))
            plan_path.write_text(json.dumps(sample_plan()))
            before = canonical.read_bytes(), plan_path.read_bytes()
            code, stdout, stderr = self.run_cli('--portfolio', canonical, '--income-plan', plan_path,
                                               '--out-dir', root)
            self.assertEqual(code, 1)
            self.assertEqual(stdout, '')
            self.assertTrue(stderr)
            self.assertFalse((root / 'income.md').exists())
            self.assertEqual((canonical.read_bytes(), plan_path.read_bytes()), before)

    def test_links_to_original_activity_resolve_the_effective_correction_once(self):
        portfolio, plan = sample_portfolio(), sample_plan()
        correction = copy.deepcopy(portfolio['activities'][0])
        correction.update(id='payment-reviewed', money={'amount': 40, 'currency': 'USD'},
                          extensions={'rikdom_correction': {'version': 1,
                              'supersedes_activity_id': 'payment-1', 'reason': 'Reviewed receipt'}})
        portfolio['activities'].append(correction)
        plan['payment_links'].append(copy.deepcopy(plan['payment_links'][0]))
        result = build_income_report(portfolio, income_plan=plan)
        match = result['planning']['reconciliation'][0]
        self.assertEqual((match['received_amount'], match['activity_ids'], match['status']),
                         (40, ['payment-reviewed'], 'partial'))
        self.assertEqual(result['monthly'][0]['gross']['total'], 40)
        self.assertEqual(result['planning']['yield_on_cost'][0]['ratio'], .04)

    def test_announcements_and_estimates_do_not_change_instrument_returns(self):
        portfolio = sample_portfolio()
        portfolio['holdings'] = [{
            'id': 'holding-1', 'quantity': 1, 'as_of': '2026-12-31',
            'market_value': {'amount': 1100, 'currency': 'USD'},
            'extensions': {'rikdom_instrument_history': {
                'status': 'complete', 'from': '2026-01-01', 'through': '2026-12-31',
                'missing_periods': [], 'notes': [],
            }},
        }]
        portfolio['activities'].append({
            'id': 'purchase-1', 'holding_id': 'holding-1', 'event_type': 'buy',
            'status': 'posted', 'effective_at': '2026-01-01T00:00:00Z', 'quantity': 1,
            'money': {'amount': 1000, 'currency': 'USD'},
        })
        before = compute_instrument_performance(portfolio, 'holding-1')
        self.assertEqual(before['status'], 'complete')
        self.assertEqual(before['profit_amount'], 150)
        portfolio['extensions'] = {'rikdom_income_plan': sample_plan()}
        planned = build_income_report(portfolio)
        self.assertEqual(planned['planning']['estimates'][0]['estimated_amount'], 999)
        self.assertEqual(compute_instrument_performance(portfolio, 'holding-1'), before)
