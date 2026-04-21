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
