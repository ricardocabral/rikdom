"""A local broker import, replay, correction and income-report contract."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rikdom.cli import main
from rikdom.storage import load_json, save_json

ROOT = Path(__file__).resolve().parents[1]


class IncomeWorkflowTests(unittest.TestCase):
    def test_import_replay_and_correction_feed_income_once_without_tax_misclassification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, out = root / 'data', root / 'out'
            canonical = data / 'portfolio.json'
            portfolio = load_json(ROOT / 'tests/fixtures/portfolio.json')
            portfolio.update(holdings=[], activities=[], extensions={}, settings={'base_currency': 'USD'})
            save_json(canonical, portfolio)
            statement = root / 'statement.xml'
            statement.write_text('''<FlexQueryResponse><FlexStatements><FlexStatement accountId="fixture" fromDate="20260101" toDate="20260131"><CashTransactions>
<CashTransaction transactionID="div" type="Dividends" description="ABC dividend" currency="USD" amount="100" symbol="ABC" dateTime="20260115;080000" />
<CashTransaction transactionID="int" type="Broker Interest Received" currency="USD" amount="5" dateTime="20260115;090000" />
<CashTransaction transactionID="tax" type="Withholding Tax" description="ABC dividend withholding tax" currency="USD" amount="-15" symbol="ABC" dateTime="20260115;100000" />
</CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>''')

            def run(*args):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main([*args, '--data-dir', str(data), '--out-root', str(out)])
                self.assertEqual(code, 0, stderr.getvalue())
                return json.loads(stdout.getvalue())

            args = ('import-statement', '--plugin', 'ibkr_flex_xml', '--plugins-dir', str(ROOT / 'plugins'),
                    '--input', str(statement), '--ingested-at', '2026-02-01T00:00:00Z', '--write')
            run(*args)
            replay = run(*args)
            self.assertEqual(replay['activities']['skipped'], 3)
            ledger = load_json(canonical)
            self.assertEqual(len(ledger['activities']), 3)
            original = copy.deepcopy(next(a for a in ledger['activities'] if a['id'] == 'ibkr-cash-div'))
            result = run('income')
            self.assertEqual(len(result['events']), 2)
            self.assertEqual(result['monthly'][0]['gross']['total'], 105)
            self.assertIsNone(result['monthly'][0]['net']['total'])

            replacement = copy.deepcopy(original)
            replacement.update(id='reviewed-div', money={'amount': 120, 'currency': 'USD'},
                               withholding_tax={'amount': 0, 'currency': 'USD'})
            replacement.pop('idempotency_key', None)
            replacement_path = root / 'replacement.json'
            save_json(replacement_path, replacement)
            correction = ('activity', 'correct', original['id'], '--input', str(replacement_path),
                          '--reason', 'Corrected source payment amount', '--write')
            run(*correction)
            run(*correction)
            before = canonical.read_bytes(), (data / 'import_log.jsonl').read_bytes()
            report = run('income', '--start', '2026-01-01', '--end', '2026-01-31')
            self.assertEqual(len(report['events']), 2)
            self.assertEqual(report['monthly'][0]['gross']['total'], 125)
            self.assertEqual(report['monthly'][0]['net']['known_subtotal'], 120)
            self.assertEqual(before, (canonical.read_bytes(), (data / 'import_log.jsonl').read_bytes()))
            current = load_json(canonical)
            self.assertEqual(current['schema_version'], '2.0.0')
            self.assertEqual(len(current['activities']), 4)
            self.assertEqual(next(a for a in current['activities'] if a['id'] == original['id']), original)
            self.assertEqual(load_json(out / 'reports' / 'income.json'), report)
            self.assertTrue((out / 'reports' / 'income.md').is_file())


if __name__ == '__main__':
    unittest.main()
