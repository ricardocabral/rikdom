from __future__ import annotations

import unittest

from rikdom.aggregate import aggregate_portfolio
from rikdom.reconciliation import Finding, ISSUE_CODES, Severity, record_finding


class ReconciliationCodesTests(unittest.TestCase):
    def test_codes_registered_with_default_severity(self) -> None:
        expected_codes = {
            "RECON_FX_MISSING",
            "TRUST_FX_FALLBACK_USED",
            "RECON_INVALID_MONEY",
            "RECON_MALFORMED_HOLDING",
            "RECON_LOOKTHROUGH_NON_POSITIVE_WEIGHT",
            "RECON_QTY_LEDGER_MISMATCH",
            "RECON_CASH_DRIFT",
        }
        self.assertEqual(expected_codes, set(ISSUE_CODES.keys()))
        for severity in ISSUE_CODES.values():
            self.assertIsInstance(severity, Severity)

    def test_finding_to_dict_omits_empty_fields(self) -> None:
        findings: list[Finding] = []
        record_finding(findings, "RECON_CASH_DRIFT", "msg")
        self.assertEqual(len(findings), 1)
        self.assertEqual(
            findings[0].to_dict(),
            {"code": "RECON_CASH_DRIFT", "severity": "warning", "message": "msg"},
        )

    def test_record_finding_no_op_when_target_is_none(self) -> None:
        record_finding(None, "RECON_CASH_DRIFT", "msg")  # must not raise


class AggregateFindingsShimTests(unittest.TestCase):
    def _stocks_catalog(self) -> list[dict]:
        return [
            {"id": "stock", "asset_class": "stocks"},
            {"id": "cash", "asset_class": "cash_equivalents"},
        ]

    def test_findings_empty_for_clean_portfolio(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": self._stocks_catalog(),
            "holdings": [
                {
                    "id": "h-1",
                    "asset_type_id": "stock",
                    "market_value": {"amount": 100.0, "currency": "BRL"},
                }
            ],
        }
        result = aggregate_portfolio(portfolio)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.findings, [])

    def test_missing_fx_emits_recon_fx_missing(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": self._stocks_catalog(),
            "holdings": [
                {
                    "id": "h-us",
                    "asset_type_id": "stock",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                }
            ],
        }
        result = aggregate_portfolio(portfolio)
        codes = [f.code for f in result.findings]
        self.assertIn("RECON_FX_MISSING", codes)
        self.assertEqual(len(result.findings), len(result.warnings))
        finding = next(f for f in result.findings if f.code == "RECON_FX_MISSING")
        self.assertEqual(finding.refs.get("holding_id"), "h-us")
        self.assertEqual(finding.severity, Severity.WARNING)

    def test_metadata_fx_fallback_emits_trust_finding(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": self._stocks_catalog(),
            "holdings": [
                {
                    "id": "h-us",
                    "asset_type_id": "stock",
                    "market_value": {"amount": 100.0, "currency": "USD"},
                    "metadata": {"fx_rate_to_base": 5.1},
                }
            ],
        }
        result = aggregate_portfolio(portfolio)
        codes = [f.code for f in result.findings]
        self.assertIn("TRUST_FX_FALLBACK_USED", codes)

    def test_quantity_drift_emits_recon_qty_finding(self) -> None:
        portfolio = {
            "settings": {"base_currency": "BRL"},
            "asset_type_catalog": self._stocks_catalog(),
            "holdings": [
                {
                    "id": "h-petr4",
                    "asset_type_id": "stock",
                    "identifiers": {"ticker": "PETR4"},
                    "quantity": 100.0,
                    "market_value": {"amount": 100.0, "currency": "BRL"},
                }
            ],
            "activities": [
                {
                    "id": "a-1",
                    "asset_type_id": "stock",
                    "instrument": {"ticker": "PETR4"},
                    "event_type": "buy",
                    "status": "posted",
                    "effective_at": "2026-04-01T00:00:00Z",
                    "quantity": 50.0,
                    "money": {"amount": 100.0, "currency": "BRL"},
                }
            ],
        }
        result = aggregate_portfolio(portfolio)
        codes = [f.code for f in result.findings]
        self.assertIn("RECON_QTY_LEDGER_MISMATCH", codes)
        f = next(x for x in result.findings if x.code == "RECON_QTY_LEDGER_MISMATCH")
        self.assertEqual(f.refs.get("holding_id"), "h-petr4")
        self.assertIn("holding_quantity", f.observed)


if __name__ == "__main__":
    unittest.main()
