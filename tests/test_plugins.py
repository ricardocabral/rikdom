from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities, merge_holdings, run_import_plugin


class PluginTests(unittest.TestCase):
    def test_csv_generic_plugin_emits_holdings_and_activities(self) -> None:
        payload = run_import_pipeline(
            plugin_name="csv-generic",
            plugins_dir="plugins",
            input_path="tests/fixtures/sample_statement.csv",
        )
        self.assertEqual(payload["provider"], "csv-generic")
        self.assertEqual(len(payload["holdings"]), 2)
        self.assertEqual(len(payload["activities"]), 3)

        dividend = next(a for a in payload["activities"] if a["id"] == "act-aapl-div-2026q1")
        self.assertEqual(dividend["event_type"], "dividend")
        self.assertEqual(dividend["money"], {"amount": 1.20, "currency": "USD"})
        self.assertEqual(dividend["instrument"]["ticker"], "AAPL")

        reimb = next(a for a in payload["activities"] if a["id"] == "act-broker-reimb-2026-03")
        self.assertEqual(reimb["event_type"], "reimbursement")

    def test_csv_generic_plugin_handles_missing_trailing_optional_holding_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/statement.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("id,asset_type_id,label,amount,currency,quantity,ticker,country,fx_rate_to_base\n")
                f.write("h-apple,stock-us,Apple,100.50,usd\n")

            payload = run_import_pipeline(
                plugin_name="csv-generic",
                plugins_dir="plugins",
                input_path=csv_path,
            )

        self.assertEqual(payload["provider"], "csv-generic")
        self.assertEqual(
            payload["holdings"],
            [
                {
                    "id": "h-apple",
                    "asset_type_id": "stock-us",
                    "label": "Apple",
                    "market_value": {"amount": 100.50, "currency": "USD"},
                }
            ],
        )

    def test_csv_generic_plugin_activity_allows_missing_trailing_optional_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/statement.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(
                    "record_type,id,event_type,amount,currency,effective_at,status,"
                    "asset_type_id,subtype,quantity,ticker,country,idempotency_key,source_ref\n"
                )
                f.write("activity,act-1,dividend,1.20,usd,2026-02-13T00:00:00Z\n")

            payload = run_import_pipeline(
                plugin_name="csv-generic",
                plugins_dir="plugins",
                input_path=csv_path,
            )

        self.assertEqual(
            payload["activities"],
            [
                {
                    "id": "act-1",
                    "event_type": "dividend",
                    "status": "posted",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "money": {"amount": 1.20, "currency": "USD"},
                }
            ],
        )

    def test_csv_generic_plugin_activity_requires_effective_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/statement.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("record_type,id,event_type,amount,currency,effective_at\n")
                f.write("activity,act-1,dividend,1.20,usd\n")

            with self.assertRaisesRegex(ValueError, "missing required effective_at"):
                run_import_pipeline(
                    plugin_name="csv-generic",
                    plugins_dir="plugins",
                    input_path=csv_path,
                )

    def test_merge_activities_is_idempotent_by_idempotency_key(self) -> None:
        portfolio: dict = {"holdings": [], "activities": []}
        imported = {
            "activities": [
                {
                    "id": "a1",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "idempotency_key": "k1",
                    "money": {"amount": 1.0, "currency": "USD"},
                }
            ]
        }

        _, counts = merge_activities(portfolio, imported)
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (1, 0, 0))
        self.assertEqual(portfolio["activities"][0]["status"], "posted")

        _, counts = merge_activities(portfolio, imported)
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (0, 0, 1))
        self.assertEqual(len(portfolio["activities"]), 1)

    def test_merge_activities_bridges_id_and_idempotency_key_indexes(self) -> None:
        portfolio: dict = {
            "holdings": [],
            "activities": [
                {
                    "id": "a1",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 1.0, "currency": "USD"},
                }
            ],
        }

        imported_with_both = {
            "activities": [
                {
                    "id": "a1",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 1.0, "currency": "USD"},
                    "idempotency_key": "idem-a1",
                }
            ]
        }
        _, counts = merge_activities(portfolio, imported_with_both)
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (0, 1, 0))
        self.assertEqual(len(portfolio["activities"]), 1)
        self.assertEqual(portfolio["activities"][0]["idempotency_key"], "idem-a1")

        portfolio_with_legacy_idem_only: dict = {
            "holdings": [],
            "activities": [
                {
                    "idempotency_key": "idem-a2",
                    "event_type": "dividend",
                    "effective_at": "2026-02-14T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 2.0, "currency": "USD"},
                }
            ],
        }

        imported_with_id_and_idem = {
            "activities": [
                {
                    "id": "a2",
                    "idempotency_key": "idem-a2",
                    "event_type": "dividend",
                    "effective_at": "2026-02-14T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 2.0, "currency": "USD"},
                }
            ]
        }

        _, counts = merge_activities(portfolio_with_legacy_idem_only, imported_with_id_and_idem)
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (0, 1, 0))
        self.assertEqual(len(portfolio_with_legacy_idem_only["activities"]), 1)
        self.assertEqual(portfolio_with_legacy_idem_only["activities"][0]["id"], "a2")

    def test_merge_activities_rejects_invalid_entries(self) -> None:
        portfolio: dict = {"holdings": [], "activities": []}
        imported = {
            "activities": [
                {
                    "id": "a1",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "status": "posted",
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "missing event_type"):
            merge_activities(portfolio, imported)

    def test_merge_activities_rejects_none_for_required_fields(self) -> None:
        portfolio: dict = {"holdings": [], "activities": []}
        imported = {
            "activities": [
                {
                    "id": "a1",
                    "event_type": None,
                    "effective_at": None,
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "missing event_type, effective_at"):
            merge_activities(portfolio, imported)

    def test_merge_activities_rejects_missing_id(self) -> None:
        portfolio: dict = {"holdings": [], "activities": []}
        imported = {
            "activities": [
                {
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "idempotency_key": "k1",
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "missing id"):
            merge_activities(portfolio, imported)

    def test_merge_activities_is_atomic_when_validation_fails(self) -> None:
        portfolio: dict = {
            "holdings": [],
            "activities": [
                {
                    "id": "existing",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 1.0, "currency": "USD"},
                }
            ],
        }
        original_activities = [dict(activity) for activity in portfolio["activities"]]
        imported = {
            "activities": [
                {
                    "id": "existing",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 2.0, "currency": "USD"},
                },
                {
                    "id": "bad",
                    "effective_at": "2026-02-13T00:00:00Z",
                },
            ]
        }

        with self.assertRaisesRegex(ValueError, "Invalid imported activity at index 1: missing event_type"):
            merge_activities(portfolio, imported)
        self.assertEqual(portfolio["activities"], original_activities)

    def test_run_import_plugin_accepts_legacy_positional_signature(self) -> None:
        with mock.patch(
            "rikdom.plugin_engine.pipeline.run_import_pipeline",
            return_value={"provider": "csv-generic", "holdings": [], "activities": []},
        ) as mock_run:
            payload = run_import_plugin("csv-generic", "input.csv", "plugins-alt")
        mock_run.assert_called_once_with("csv-generic", "plugins-alt", "input.csv")
        self.assertEqual(payload["provider"], "csv-generic")

    def test_merge_holdings_ignores_missing_holdings_key(self) -> None:
        portfolio: dict = {"holdings": []}
        _, counts = merge_holdings(portfolio, {"activities": []})
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
