from __future__ import annotations

import copy
import tempfile
import unittest

from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import build_import_diff, merge_activities, merge_holdings


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

    def test_csv_generic_plugin_holding_rejects_missing_required_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/statement.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("id,asset_type_id,label,amount\n")
                f.write("h-apple,stock-us,Apple,100.50\n")

            with self.assertRaisesRegex(
                ValueError,
                r"Invalid holding row: missing required column 'currency'",
            ):
                run_import_pipeline(
                    plugin_name="csv-generic",
                    plugins_dir="plugins",
                    input_path=csv_path,
                )

    def test_csv_generic_plugin_holding_rejects_empty_required_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/statement.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("id,asset_type_id,label,amount,currency\n")
                f.write("h-apple,stock-us,,100.50,usd\n")

            with self.assertRaisesRegex(
                ValueError,
                r"Invalid holding row: required field 'label' is empty",
            ):
                run_import_pipeline(
                    plugin_name="csv-generic",
                    plugins_dir="plugins",
                    input_path=csv_path,
                )

    def test_csv_generic_plugin_activity_rejects_missing_required_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/statement.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("record_type,id,event_type,amount,effective_at\n")
                f.write("activity,act-1,dividend,1.20,2026-02-13T00:00:00Z\n")

            with self.assertRaisesRegex(
                ValueError,
                r"Invalid activity row: missing required column 'currency'",
            ):
                run_import_pipeline(
                    plugin_name="csv-generic",
                    plugins_dir="plugins",
                    input_path=csv_path,
                )

    def test_csv_generic_plugin_activity_rejects_empty_required_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/statement.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("record_type,id,event_type,amount,currency,effective_at\n")
                f.write("activity,,dividend,1.20,usd,2026-02-13T00:00:00Z\n")

            with self.assertRaisesRegex(
                ValueError,
                r"Invalid activity row: required field 'id' is empty",
            ):
                run_import_pipeline(
                    plugin_name="csv-generic",
                    plugins_dir="plugins",
                    input_path=csv_path,
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

    def test_build_import_diff_reports_create_update_noop(self) -> None:
        portfolio: dict = {
            "holdings": [
                {
                    "id": "h-1",
                    "asset_type_id": "stock",
                    "label": "Apple",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                }
            ],
            "activities": [
                {
                    "id": "a-1",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 1.0, "currency": "USD"},
                    "idempotency_key": "k-1",
                }
            ],
        }
        imported = {
            "holdings": [
                {
                    "id": "h-1",
                    "asset_type_id": "stock",
                    "label": "Apple Inc.",
                    "market_value": {"amount": 110.0, "currency": "USD"},
                },
                {
                    "id": "h-2",
                    "asset_type_id": "stock",
                    "label": "Microsoft",
                    "market_value": {"amount": 200.0, "currency": "USD"},
                },
            ],
            "activities": [
                {
                    "id": "a-1",
                    "event_type": "dividend",
                    "effective_at": "2026-02-13T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 1.0, "currency": "USD"},
                    "idempotency_key": "k-1",
                },
                {
                    "id": "a-2",
                    "event_type": "buy",
                    "effective_at": "2026-02-14T00:00:00Z",
                    "status": "posted",
                    "money": {"amount": 200.0, "currency": "USD"},
                },
            ],
        }

        report = build_import_diff(portfolio, imported)
        self.assertEqual(report["summary"]["holdings"], {"create": 1, "update": 1, "noop": 0})
        self.assertEqual(report["summary"]["activities"], {"create": 1, "update": 0, "noop": 1})
        holding_update = next(
            row
            for row in report["rows"]
            if row["entity_type"] == "holding" and row["id"] == "h-1"
        )
        self.assertEqual(holding_update["operation"], "update")
        self.assertTrue(any(change["field"] == "label" for change in holding_update["changes"]))

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
        original_activities = copy.deepcopy(portfolio["activities"])
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

    def test_merge_holdings_ignores_missing_holdings_key(self) -> None:
        portfolio: dict = {"holdings": []}
        _, counts = merge_holdings(portfolio, {"activities": []})
        self.assertEqual((counts.inserted, counts.updated, counts.skipped), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()


class TaxLotImportTests(unittest.TestCase):
    def test_merge_preserves_history_and_provenance_on_repeat(self):
        from rikdom import plugins
        imported = {'tax_lots': [{'id': 'lot', 'holding_id': 'h', 'acquired_at': '2025-01-01T00:00:00Z', 'quantity': 10, 'cost_basis': {'amount': 90, 'currency': 'BRL'}, 'extensions': {'history': ['acquired']}}]}
        plugins.stamp_provenance(imported, source_system='broker', import_run_id='one', ingested_at='2026-01-01T00:00:00Z')
        p, counts = plugins.merge_tax_lots({'holdings': [{'id': 'h'}]}, imported)
        self.assertEqual(counts.inserted, 1)
        first = copy.deepcopy(p)
        plugins.stamp_provenance(imported, source_system='broker', import_run_id='two', ingested_at='2026-01-02T00:00:00Z')
        p, counts = plugins.merge_tax_lots(p, imported)
        self.assertEqual(counts.skipped, 1)
        self.assertEqual(p, first)
        self.assertEqual(p['tax_lots'][0]['provenance']['source_system'], 'broker')
        self.assertEqual(plugins.build_import_diff(p, imported)['summary']['tax_lots']['noop'], 1)

    def test_tax_lot_identity_preserved_when_broker_changes_row_id(self):
        from rikdom import plugins
        old = {'id': 'original', 'holding_id': 'h', 'acquired_at': '2025-01-01T00:00:00Z', 'quantity': 10, 'cost_basis': {'amount': 90, 'currency': 'BRL'}, 'provenance': {'idempotency_key': 'stable'}, 'metadata': {'audit': 'keep'}}
        incoming = dict(old, id='new-row', quantity=5)
        incoming.pop('metadata')
        p, counts = plugins.merge_tax_lots({'holdings': [{'id': 'h'}], 'tax_lots': [old]}, {'tax_lots': [incoming]})
        self.assertEqual(counts.updated, 1)
        self.assertEqual(len(p['tax_lots']), 1)
        self.assertEqual(p['tax_lots'][0]['id'], 'original')
        self.assertEqual(p['tax_lots'][0]['metadata'], {'audit': 'keep'})

    def test_invalid_tax_lot_references_rejected_without_partial_merge(self):
        from rikdom import plugins
        p = {'holdings': [{'id': 'h'}], 'tax_lots': []}
        lot = {'id': 'lot', 'holding_id': 'missing', 'acquired_at': '2025-01-01T00:00:00Z', 'quantity': 10, 'cost_basis': {'amount': 90, 'currency': 'BRL'}}
        with self.assertRaises(ValueError):
            plugins.merge_tax_lots(p, {'tax_lots': [lot]})
        self.assertEqual(p['tax_lots'], [])

    def test_holding_value_update_preserves_declared_instrument_history(self):
        history = {'status': 'partial', 'from': '2025-01-01', 'through': '2026-01-01', 'notes': ['missing early trades']}
        h = {'id': 'h', 'asset_type_id': 'fii', 'label': 'Fund', 'market_value': {'amount': 90, 'currency': 'BRL'}, 'extensions': {'rikdom_instrument_history': history, 'custom': True}, 'provenance': {'source_ref': 'original-statement'}}
        incoming = {'id': 'h', 'asset_type_id': 'fii', 'label': 'Fund', 'market_value': {'amount': 100, 'currency': 'BRL'}}
        p, counts = merge_holdings({'holdings': [h]}, {'holdings': [incoming]})
        self.assertEqual(counts.updated, 1)
        self.assertEqual(p['holdings'][0]['extensions'], {'rikdom_instrument_history': history, 'custom': True})
        self.assertEqual(p['holdings'][0]['provenance']['source_ref'], 'original-statement')

        p, repeat = merge_holdings(p, {"holdings": [incoming]})
        self.assertEqual(repeat.skipped, 1)
        self.assertEqual(repeat.updated, 0)

    def test_holding_metadata_aliases_survive_valuation_import_and_repeat(self):
        holding = {'id': 'h', 'asset_type_id': 'fii', 'label': 'Fund', 'market_value': {'amount': 90, 'currency': 'BRL'}, 'metadata': {'instrument_aliases': ['OLD11'], 'user_note': 'keep'}}
        incoming = {'id': 'h', 'asset_type_id': 'fii', 'label': 'Fund', 'market_value': {'amount': 100, 'currency': 'BRL'}, 'metadata': {'broker_note': 'new'}}
        p = {'holdings': [holding]}
        diff = build_import_diff(p, {'holdings': [incoming]})
        self.assertFalse(any(change['field'] in ('metadata.instrument_aliases', 'metadata.user_note') for change in diff['rows'][0]['changes']))
        p, counts = merge_holdings(p, {'holdings': [incoming]})
        self.assertEqual(counts.updated, 1)
        self.assertEqual(p['holdings'][0]['metadata'], {'instrument_aliases': ['OLD11'], 'user_note': 'keep', 'broker_note': 'new'})
        self.assertEqual(build_import_diff(p, {'holdings': [incoming]})['summary']['holdings'], {'create': 0, 'update': 0, 'noop': 1})
        p, counts = merge_holdings(p, {'holdings': [incoming]})
        self.assertEqual(counts.skipped, 1)

    def test_tax_lot_conflicting_id_and_idempotency_key_rejected_atomically(self):
        from rikdom.plugins import merge_tax_lots
        first = {'id': 'one', 'holding_id': 'h', 'acquired_at': '2025-01-01T00:00:00Z', 'quantity': 1, 'cost_basis': {'amount': 90, 'currency': 'BRL'}, 'provenance': {'idempotency_key': 'key-one'}}
        second = dict(first, id='two', provenance={'idempotency_key': 'key-two'})
        portfolio = {'holdings': [{'id': 'h'}], 'tax_lots': [first, second]}
        before = copy.deepcopy(portfolio)
        incoming = {'tax_lots': [dict(first, id='three', provenance={'idempotency_key': 'key-three'}), dict(first, provenance={'idempotency_key': 'key-two'})]}
        with self.assertRaisesRegex(ValueError, 'Conflicting tax lot identity'):
            merge_tax_lots(portfolio, incoming)
        self.assertEqual(portfolio, before)
        with self.assertRaisesRegex(ValueError, 'Conflicting tax lot identity'):
            build_import_diff(portfolio, incoming)

    def test_renamed_lot_references_rejected_before_mutation(self):
        from rikdom.plugins import merge_tax_lots
        from rikdom.import_preflight import build_preflight_report
        old = {'id': 'stable-lot', 'holding_id': 'h', 'acquired_at': '2025-01-01T00:00:00Z', 'quantity': 1, 'cost_basis': {'amount': 90, 'currency': 'BRL'}, 'provenance': {'idempotency_key': 'broker-lot'}}
        for corporate in (False, True):
            with self.subTest(corporate=corporate):
                activity = {'id': 'sale', 'event_type': 'sell', 'effective_at': '2026-01-01T00:00:00Z', 'tax_lot_ids': ['incoming-lot']}
                if corporate:
                    activity.pop('tax_lot_ids')
                    activity['corporate_action'] = {'kind': 'merger', 'legs': [{'holding_id': 'h', 'quantity_delta': -1, 'tax_lot_ids': ['incoming-lot']}]}
                imported = {'tax_lots': [dict(old, id='incoming-lot')], 'activities': [activity]}
                p = {'holdings': [{'id': 'h'}], 'tax_lots': [copy.deepcopy(old)]}
                before = copy.deepcopy(p)
                report = build_preflight_report(p, imported)
                self.assertFalse(report['ok'])
                self.assertTrue(any('stable-lot' in issue['message'] and 'incoming-lot' in issue['message'] for issue in report['issues']))
                with self.assertRaisesRegex(ValueError, 'incoming-lot'):
                    merge_tax_lots(p, imported)
                self.assertEqual(p, before)
                refs = activity['corporate_action']['legs'][0]['tax_lot_ids'] if corporate else activity['tax_lot_ids']
                refs[:] = ['stable-lot']
                self.assertTrue(build_preflight_report(p, imported)['ok'])
                merged, counts = merge_tax_lots(p, imported)
                self.assertEqual(merged['tax_lots'][0]['id'], 'stable-lot')
                self.assertEqual(counts.skipped, 1)
