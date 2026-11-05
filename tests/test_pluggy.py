from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from rikdom.cli import main
from rikdom.plugin_engine.pipeline import (
    run_import_pipeline,
    run_connector_describe_pipeline,
)
from rikdom.plugins import merge_activities, merge_holdings


ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
ITEM = "11111111-1111-4111-8111-111111111111"
INVESTMENT = "22222222-2222-4222-8222-222222222222"
ACCOUNT = "33333333-3333-4333-8333-333333333333"


def snapshot():
    return {
        "format": "pluggy-portfolio-v1",
        "fetched_at": "2026-11-04T15:00:00Z",
        "include_transactions": True,
        "include_bank_accounts": True,
        "items": [
            {
                "item": {
                    "id": ITEM,
                    "status": "UPDATED",
                    "executionStatus": "SUCCESS",
                    "consentExpiresAt": "2099-01-01T00:00:00Z",
                    "lastUpdatedAt": "2026-11-04T14:00:00Z",
                    "connector": {"id": 200, "name": "MeuPluggy"},
                },
                "accounts": [
                    {
                        "id": ACCOUNT,
                        "itemId": ITEM,
                        "type": "BANK",
                        "subtype": "CHECKING_ACCOUNT",
                        "name": "Checking",
                        "balance": 50,
                        "currencyCode": "BRL",
                        "updatedAt": "2026-11-04T14:00:00Z",
                    }
                ],
                "investments": [
                    {
                        "id": INVESTMENT,
                        "itemId": ITEM,
                        "name": "Example stock",
                        "code": "PETR4",
                        "type": "EQUITY",
                        "subtype": "STOCK",
                        "quantity": 10,
                        "value": 12,
                        "amount": 120,
                        "balance": 115,
                        "taxes": 5,
                        "taxes2": None,
                        "currencyCode": "BRL",
                        "date": "2026-11-03T00:00:00Z",
                        "status": "ACTIVE",
                        "owner": "Synthetic owner",
                        "customProviderField": {"a": 1},
                    }
                ],
                "investment_transactions": {
                    INVESTMENT: [
                        {
                            "id": "trade-1",
                            "type": "BUY",
                            "movementType": "CREDIT",
                            "quantity": 10,
                            "amount": 100,
                            "netAmount": 102,
                            "value": 10,
                            "date": "2026-10-01T00:00:00Z",
                            "tradeDate": "2026-10-01T00:00:00Z",
                            "expenses": {"brokerageFee": 2, "incomeTax": 0},
                        },
                        {
                            "id": "income-1",
                            "type": "INTEREST",
                            "movementType": "DEBIT",
                            "amount": 5,
                            "netAmount": 4,
                            "date": "2026-10-15T00:00:00Z",
                            "expenses": {"incomeTax": 1},
                        },
                    ]
                },
            }
        ],
    }


class PluggyImportTests(unittest.TestCase):
    def parse(self, data=None, mappings=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text(json.dumps(snapshot() if data is None else data))
            if mappings is not None:
                config = Path(tmp) / "import.json"
                config.write_text(
                    json.dumps({"snapshot": "snapshot.json", "mappings": mappings})
                )
                path = config
            return run_import_pipeline("pluggy", str(PLUGINS), str(path))

    def test_plugin_is_available(self):
        self.assertTrue((PLUGINS / "pluggy" / "plugin.json").is_file())

    def test_gross_net_dates_and_unknown_provider_fields_are_preserved(self):
        payload = self.parse()
        holding = next(
            h
            for h in payload["holdings"]
            if h["id"] == f"pluggy:investment:{INVESTMENT}"
        )
        self.assertEqual(holding["market_value"], {"amount": 120, "currency": "BRL"})
        self.assertEqual(holding["valuation"]["net_value"]["amount"], 115)
        self.assertEqual(holding["as_of"], "2026-11-03T00:00:00Z")
        self.assertEqual(holding["quantity"], 10)
        self.assertEqual(holding["metadata"]["pluggy"]["customProviderField"], {"a": 1})
        self.assertNotIn("unit_cost", holding)
        self.assertNotIn("account_id", holding)
        schema = json.loads((ROOT / "schema/plugin-statement.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)

    def test_missing_gross_value_does_not_promote_net_to_gross(self):
        data = snapshot()
        data["items"][0]["investments"][0]["amount"] = None
        payload = self.parse(data)
        self.assertEqual(len(payload["holdings"]), 1)  # bank cash only
        self.assertEqual(len(payload["activities"]), 2)
        self.assertTrue(all("holding_id" not in a for a in payload["activities"]))
        self.assertEqual(payload["activities"][0]["instrument"]["ticker"], "PETR4")
        self.assertTrue(
            payload["metadata"]["rikdom_import_diagnostics"]["unsupported_events"]
        )

    def test_nullable_quantity_stays_unknown(self):
        data = snapshot()
        data["items"][0]["investments"][0]["quantity"] = None
        holding = next(
            h for h in self.parse(data)["holdings"] if "investment" in h["id"]
        )
        self.assertIsNone(holding["quantity"])

    def test_pending_positions_are_not_asserted_as_settled(self):
        data = snapshot()
        data["items"][0]["investments"][0]["status"] = "PENDING"
        payload = self.parse(data)
        self.assertEqual(len(payload["holdings"]), 1)
        self.assertEqual(payload["activities"], [])

    def test_explicit_total_withdrawal_closes_position_without_synthetic_sale(self):
        data = snapshot()
        inv = data["items"][0]["investments"][0]
        inv.update(status="TOTAL_WITHDRAWAL", amount=0, balance=0, quantity=0)
        payload = self.parse(data)
        holding = next(h for h in payload["holdings"] if "investment" in h["id"])
        self.assertEqual(holding["market_value"]["amount"], 0)
        self.assertEqual(len(payload["activities"]), 2)

    def test_trade_directions_and_income_classification_are_conservative(self):
        payload = self.parse()
        buy, income = payload["activities"]
        self.assertEqual(buy["event_type"], "buy")
        self.assertEqual(buy["money"]["amount"], 100)
        self.assertEqual(buy["fees"]["amount"], 2)
        self.assertEqual(buy["settled_at"], "2026-10-01T00:00:00Z")
        self.assertNotIn("trade_at", buy)
        # Pluggy INTEREST includes dividends, JCP and rent: no precise class is asserted.
        self.assertEqual(income["event_type"], "income")
        self.assertEqual(income["money"]["amount"], 5)
        self.assertEqual(income["withholding_tax"]["amount"], 1)
        self.assertEqual(income["metadata"]["rikdom_income"]["amount_basis"], "gross")
        self.assertEqual(buy["metadata"]["rikdom_source_identity"]["kind"], "source")

    def test_inconsistent_closed_position_is_diagnosed_not_zeroed_or_counted(self):
        data = snapshot()
        data["items"][0]["investments"][0].update(status="TOTAL_WITHDRAWAL", quantity=0)
        payload = self.parse(data)
        self.assertEqual(len(payload["holdings"]), 1)
        diagnostic = payload["metadata"]["rikdom_import_diagnostics"][
            "unsupported_events"
        ][0]
        self.assertIn("nonzero", diagnostic["reason"])
        self.assertEqual(len(diagnostic["metadata"]["investment_transactions"]), 2)

    def test_open_finance_other_taxes_and_iof_provision_are_not_fees(self):
        data = snapshot()
        tx = data["items"][0]["investment_transactions"][INVESTMENT][1]
        tx["expenses"] = {
            "incomeTax": 1,
            "other": 0.25,
            "iof": 0.5,
            "iofProvision": 7,
            "brokerageFee": 0.1,
        }
        activity = self.parse(data)["activities"][1]
        self.assertEqual(activity["fees"]["amount"], 0.1)
        self.assertEqual(activity["withholding_tax"]["amount"], 1.75)

    def test_all_asset_types_and_bank_reserves_do_not_create_extra_positions(self):
        for raw_type, subtype, expected in [
            ("EQUITY", "STOCK", "pluggy_stock"),
            ("EQUITY", "REAL_ESTATE_FUND", "pluggy_fii"),
            ("ETF", "ETF", "pluggy_fund"),
            ("MUTUAL_FUND", "MULTIMARKET_FUND", "pluggy_fund"),
            ("FIXED_INCOME", "TREASURY", "pluggy_fixed_income"),
            ("SECURITY", "PGBL", "pluggy_retirement"),
            ("COE", "STRUCTURED_NOTE", "pluggy_structured_note"),
            ("FUTURE_TYPE", "OTHER", "pluggy_other"),
        ]:
            with self.subTest(raw_type=raw_type):
                data = snapshot()
                data["items"][0]["investments"][0].update(
                    type=raw_type, subtype=subtype
                )
                data["items"][0]["accounts"][0]["bankData"] = {
                    "automaticallyInvestedBalance": 10,
                    "reservedBalances": [{"amount": 10}],
                }
                payload = self.parse(data)
                self.assertEqual(len(payload["holdings"]), 2)
                self.assertEqual(payload["holdings"][1]["asset_type_id"], expected)

    def test_sell_tax_amortization_and_nullable_transfer(self):
        data = snapshot()
        txs = data["items"][0]["investment_transactions"][INVESTMENT]
        txs.clear()
        for i, (kind, direction, amount) in enumerate(
            [
                ("SELL", "DEBIT", 4),
                ("TAX", "DEBIT", 1),
                ("AMORTIZATION", "DEBIT", 2),
                ("TRANSFER", "CREDIT", None),
                ("TRANSFER", "DEBIT", None),
            ]
        ):
            txs.append(
                {
                    "id": f"t{i}",
                    "type": kind,
                    "movementType": direction,
                    "amount": amount,
                    "date": "2026-11-01T00:00:00Z",
                    "quantity": 1,
                }
            )
        activities = self.parse(data)["activities"]
        self.assertEqual(
            [a["event_type"] for a in activities],
            ["sell", "tax_withheld", "amortization", "transfer_in", "transfer_out"],
        )
        self.assertEqual(activities[1]["money"]["amount"], 1)
        self.assertNotIn("money", activities[3])

    def test_tax_cost_is_consumed_by_instrument_performance(self):
        from rikdom.instrument_performance import compute_instrument_performance

        data = snapshot()
        data["items"][0]["investment_transactions"][INVESTMENT].append(
            {"id": "tax-1", "type": "TAX", "amount": 3, "date": "2026-10-20T00:00:00Z"}
        )
        payload = self.parse(data)
        portfolio = {
            "holdings": payload["holdings"],
            "activities": payload["activities"],
        }
        report = compute_instrument_performance(
            portfolio, f"pluggy:investment:{INVESTMENT}"
        )
        self.assertEqual(report["observed_taxes"], 4)
        self.assertFalse(
            any("nonnegative" in warning for warning in report["warnings"])
        )

    def test_offline_transactions_cannot_claim_a_different_investment_or_item(self):
        for field in ("investmentId", "itemId"):
            with self.subTest(field=field):
                data = snapshot()
                data["items"][0]["investment_transactions"][INVESTMENT][0][field] = (
                    "other"
                )
                with self.assertRaisesRegex(ValueError, "ownership|different"):
                    self.parse(data)

    def test_reviewed_income_classification_and_overlap_exclusion(self):
        payload = self.parse(
            mappings={
                "transactions": {
                    "trade-1": {"skip": True},
                    "income-1": {"event_type": "dividend"},
                }
            }
        )
        self.assertEqual([a["event_type"] for a in payload["activities"]], ["dividend"])
        self.assertTrue(
            payload["metadata"]["rikdom_import_diagnostics"]["unsupported_events"]
        )

    def test_position_disappearance_does_not_delete_existing_holding(self):
        first = self.parse()
        portfolio = {"holdings": [], "activities": []}
        merge_holdings(portfolio, first)
        data = snapshot()
        data["items"][0]["investments"] = []
        data["items"][0]["investment_transactions"] = {}
        merge_holdings(portfolio, self.parse(data))
        self.assertEqual(len(portfolio["holdings"]), 2)

    def test_renewed_item_retains_provider_transaction_identity(self):
        first = self.parse()
        portfolio = {"holdings": [], "activities": []}
        merge_holdings(portfolio, first)
        merge_activities(portfolio, first)
        data = snapshot()
        new_item = "44444444-4444-4444-8444-444444444444"
        data["items"][0]["item"]["id"] = new_item
        for row in [*data["items"][0]["accounts"], *data["items"][0]["investments"]]:
            row["itemId"] = new_item
        merge_holdings(portfolio, self.parse(data))
        merge_activities(portfolio, self.parse(data))
        self.assertEqual(
            (len(portfolio["holdings"]), len(portfolio["activities"])), (2, 2)
        )

    def test_unknown_and_idless_transactions_are_visible_without_fabricated_ids(self):
        data = snapshot()
        txs = data["items"][0]["investment_transactions"][INVESTMENT]
        txs.extend(
            [
                {
                    "id": "unknown-1",
                    "type": "SPLIT",
                    "date": "2026-11-01T00:00:00Z",
                    "quantity": 10,
                },
                {"type": "BUY", "date": "2026-11-01T00:00:00Z", "amount": 10},
            ]
        )
        payload = self.parse(data)
        self.assertEqual(len(payload["activities"]), 2)
        unsupported = payload["metadata"]["rikdom_import_diagnostics"][
            "unsupported_events"
        ]
        self.assertEqual(len(unsupported), 2)

    def test_missing_transaction_page_cannot_become_empty_history(self):
        data = snapshot()
        del data["items"][0]["investment_transactions"][INVESTMENT]
        with self.assertRaisesRegex(ValueError, "transactions"):
            self.parse(data)

    def test_repeated_and_reordered_imports_do_not_duplicate(self):
        first = self.parse()
        portfolio = {"holdings": [], "activities": []}
        merge_holdings(portfolio, first)
        merge_activities(portfolio, first)
        data = snapshot()
        data["items"][0]["investment_transactions"][INVESTMENT].reverse()
        data["fetched_at"] = "2026-11-05T15:00:00Z"
        second = self.parse(data)
        _, holdings = merge_holdings(portfolio, second)
        _, activities = merge_activities(portfolio, second)
        self.assertEqual(
            (len(portfolio["holdings"]), len(portfolio["activities"])), (2, 2)
        )
        self.assertEqual(
            (
                holdings.inserted,
                holdings.updated,
                activities.inserted,
                activities.updated,
            ),
            (0, 0, 0, 0),
        )

    def test_mapped_existing_holding_keeps_activity_reference_and_account(self):
        mappings = {
            "items": {ITEM: {"account_id": "broker-a"}},
            "investments": {
                INVESTMENT: {
                    "holding_id": "existing-position",
                    "asset_type_id": "stock",
                }
            },
        }
        payload = self.parse(mappings=mappings)
        holding = next(h for h in payload["holdings"] if h["id"] == "existing-position")
        self.assertEqual(holding["account_id"], "broker-a")
        self.assertTrue(
            all(a["holding_id"] == "existing-position" for a in payload["activities"])
        )
        portfolio = {
            "holdings": [{**holding, "market_value": {"amount": 90, "currency": "BRL"}}]
        }
        merge_holdings(portfolio, payload)
        self.assertEqual(len(portfolio["holdings"]), 2)

    def test_distinct_accounts_with_the_same_ticker_stay_distinct(self):
        data = snapshot()
        second = copy.deepcopy(data["items"][0])
        second["item"]["id"] = "44444444-4444-4444-8444-444444444444"
        second["accounts"] = []
        inv = second["investments"][0]
        inv.update(
            id="55555555-5555-4555-8555-555555555555", itemId=second["item"]["id"]
        )
        second["investment_transactions"] = {inv["id"]: []}
        data["items"].append(second)
        payload = self.parse(data)
        self.assertEqual(len(payload["holdings"]), 3)

    def test_conflicting_duplicate_records_and_noninjective_mappings_fail(self):
        data = snapshot()
        inv = data["items"][0]["investments"][0]
        data["items"][0]["investments"].append({**inv, "amount": 999})
        with self.assertRaisesRegex(ValueError, "conflict|duplicate"):
            self.parse(data)
        data = snapshot()
        with self.assertRaisesRegex(ValueError, "mapping|holding"):
            self.parse(
                data,
                {
                    "investments": {INVESTMENT: {"holding_id": "same"}},
                    "accounts": {ACCOUNT: {"holding_id": "same"}},
                },
            )

    def test_invalid_financial_values_fail_without_silent_coercion(self):
        for field, value in [
            ("amount", True),
            ("amount", "120,00"),
            ("quantity", -1),
            ("currencyCode", "B/L"),
            ("date", "not-a-date"),
        ]:
            with self.subTest(field=field, value=value):
                data = snapshot()
                data["items"][0]["investments"][0][field] = value
                with self.assertRaises(ValueError):
                    self.parse(data)

    def test_connector_envelope_can_be_replayed(self):
        payload = self.parse(
            {"plugin": {"name": "pluggy"}, "operation": "portfolio", "data": snapshot()}
        )
        self.assertEqual(len(payload["holdings"]), 2)

    def test_description_does_not_require_credentials(self):
        description = run_connector_describe_pipeline("pluggy", str(PLUGINS))
        self.assertTrue(description["readOnly"])
        self.assertIn("portfolio", description["operations"])

    def test_cli_reimport_and_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio = json.loads((ROOT / "tests/fixtures/portfolio.json").read_text())
            portfolio.update(holdings=[], activities=[])
            portfolio["settings"]["base_currency"] = "BRL"
            path = root / "portfolio.json"
            path.write_text(json.dumps(portfolio))
            source = root / "snapshot.json"
            source.write_text(json.dumps(snapshot()))
            args = [
                "import-statement",
                "--portfolio",
                str(path),
                "--plugin",
                "pluggy",
                "--plugins-dir",
                str(PLUGINS),
                "--input",
                str(source),
                "--out-root",
                str(root / "out"),
                "--import-log",
                str(root / "imports.jsonl"),
            ]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([*args, "--dry-run"]), 0)
            self.assertEqual(json.loads(path.read_text())["holdings"], [])
            for _ in range(2):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main([*args, "--write", "--reconcile"])
                self.assertEqual(code, 0, err.getvalue() + out.getvalue())
                report = json.loads(out.getvalue())
                self.assertEqual(report["reconciliation"]["status"], "computed")
            stored = json.loads(path.read_text())
            self.assertEqual(
                (len(stored["holdings"]), len(stored["activities"])), (2, 2)
            )
            self.assertEqual(report["holdings"]["inserted"], 0)
            self.assertEqual(report["activities"]["inserted"], 0)
            self.assertTrue((root / "out/reports/reconciliation.json").is_file())


if __name__ == "__main__":
    unittest.main()
