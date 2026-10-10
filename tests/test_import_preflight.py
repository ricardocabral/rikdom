from __future__ import annotations

import unittest

from rikdom.import_preflight import build_preflight_report


class ImportPreflightTests(unittest.TestCase):
    def test_reports_blocking_and_non_blocking_issues(self) -> None:
        portfolio = {
            "holdings": [{"id": "h-existing"}],
            "activities": [{"id": "a-existing", "idempotency_key": "idem-existing"}],
        }
        imported = {
            "holdings": [
                {
                    "id": "h-existing",
                    "asset_type_id": "stock",
                    "label": "Existing Holding",
                    "market_value": {"amount": 100, "currency": "USD"},
                },
                {
                    "id": "h-bad",
                    "asset_type_id": "stock",
                    "label": "Bad Currency",
                    "market_value": {"amount": 100, "currency": "USDX"},
                },
            ],
            "activities": [
                {
                    "id": "a-existing",
                    "event_type": "dividend",
                    "effective_at": "bad-date",
                    "idempotency_key": "idem-existing",
                }
            ],
        }

        report = build_preflight_report(portfolio, imported)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("INVALID_CURRENCY", codes)
        self.assertIn("DATE_PARSE_FAILED", codes)
        self.assertIn("DUPLICATE_EXISTING", codes)
        self.assertFalse(report["ok"])
        self.assertGreater(report["summary"]["blocking_issues"], 0)


if __name__ == "__main__":
    unittest.main()


class HistoryPreflightTests(unittest.TestCase):
    def test_tax_lots_report_rows_and_block_unknown_holdings(self):
        lot = {'id': 'lot', 'holding_id': 'missing', 'acquired_at': '2025-01-01T00:00:00Z', 'quantity': 1, 'cost_basis': {'amount': 90, 'currency': 'BRL'}}
        report = build_preflight_report({'holdings': []}, {'tax_lots': [lot]})
        self.assertFalse(report['ok'])
        self.assertEqual(report['rows'][0]['row_key'], 'tax_lot:lot')
        self.assertTrue(any(i.get('field') == 'holding_id' for i in report['issues']))

    def test_corporate_action_references_resolve_within_same_import(self):
        h = {'id': 'h', 'asset_type_id': 'fii', 'label': 'Fund', 'market_value': {'amount': 90, 'currency': 'BRL'}}
        a = {'id': 'm', 'event_type': 'merger', 'effective_at': '2026-01-01T00:00:00Z', 'settled_at': 'bad', 'corporate_action': {'kind': 'merger', 'legs': [{'holding_id': 'h', 'quantity_delta': 1}]}}
        report = build_preflight_report({'holdings': []}, {'holdings': [h], 'activities': [a]})
        self.assertFalse(report['ok'])
        self.assertTrue(any(i.get('field') == 'settled_at' for i in report['issues']))
        a['settled_at'] = '2026-01-02T00:00:00Z'
        self.assertTrue(build_preflight_report({'holdings': []}, {'holdings': [h], 'activities': [a]})['ok'])

    def test_malformed_history_collections_return_blocking_report(self):
        for key in ['holdings', 'activities', 'tax_lots']:
            with self.subTest(key=key):
                report = build_preflight_report({'holdings': []}, {key: 42})
                self.assertFalse(report['ok'])
                self.assertEqual(report['issues'][0]['code'], 'INVALID_COLLECTION_TYPE')
