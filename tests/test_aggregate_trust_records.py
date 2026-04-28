from __future__ import annotations

import unittest

from rikdom.aggregate import aggregate_portfolio


def _catalog() -> list[dict]:
    return [
        {"id": "stock", "asset_class": "equity"},
        {"id": "cash", "asset_class": "cash_equivalents"},
    ]


def _portfolio(holdings: list[dict], settings: dict | None = None) -> dict:
    return {
        "settings": settings or {"base_currency": "USD"},
        "asset_type_catalog": _catalog(),
        "holdings": holdings,
        "activities": [],
    }


class HoldingTrustRecordTests(unittest.TestCase):
    def test_identity_conversion_records_rate_one(self) -> None:
        result = aggregate_portfolio(
            _portfolio(
                [
                    {
                        "id": "h1",
                        "asset_type_id": "stock",
                        "quantity": 1,
                        "market_value": {"amount": 100.0, "currency": "USD"},
                    }
                ]
            )
        )

        self.assertEqual(len(result.trust_records), 1)
        record = result.trust_records[0]
        self.assertEqual(record.holding_id, "h1")
        self.assertEqual(record.asset_type_id, "stock")
        self.assertEqual(record.asset_class, "equity")
        self.assertEqual(record.source_amount, 100.0)
        self.assertEqual(record.source_currency, "USD")
        self.assertEqual(record.base_currency, "USD")
        self.assertEqual(record.base_amount, 100.0)
        self.assertEqual(record.fx_rate, 1.0)
        self.assertEqual(record.fx_source, "identity")
        self.assertIsNone(record.excluded_reason)
        self.assertEqual(record.findings, [])

    def test_fx_rates_to_base_source_recorded(self) -> None:
        result = aggregate_portfolio(
            _portfolio(
                [
                    {
                        "id": "h1",
                        "asset_type_id": "stock",
                        "quantity": 1,
                        "market_value": {"amount": 100.0, "currency": "EUR"},
                    }
                ]
            ),
            fx_rates_to_base={"EUR": 1.1},
        )

        self.assertEqual(len(result.trust_records), 1)
        record = result.trust_records[0]
        self.assertEqual(record.source_currency, "EUR")
        self.assertEqual(record.fx_rate, 1.1)
        self.assertEqual(record.fx_source, "fx_rates_to_base")
        self.assertAlmostEqual(record.base_amount or 0.0, 110.0)

    def test_metadata_fallback_recorded_with_finding(self) -> None:
        result = aggregate_portfolio(
            _portfolio(
                [
                    {
                        "id": "h1",
                        "asset_type_id": "stock",
                        "quantity": 1,
                        "market_value": {"amount": 100.0, "currency": "EUR"},
                        "metadata": {"fx_rate_to_base": 1.2},
                    }
                ]
            )
        )

        self.assertEqual(len(result.trust_records), 1)
        record = result.trust_records[0]
        self.assertEqual(record.fx_source, "metadata.fx_rate_to_base")
        self.assertEqual(record.fx_rate, 1.2)
        self.assertIn("TRUST_FX_FALLBACK_USED", record.findings)

    def test_missing_fx_marks_excluded_and_links_finding(self) -> None:
        result = aggregate_portfolio(
            _portfolio(
                [
                    {
                        "id": "h1",
                        "asset_type_id": "stock",
                        "quantity": 1,
                        "market_value": {"amount": 100.0, "currency": "EUR"},
                    }
                ]
            )
        )

        self.assertEqual(len(result.trust_records), 1)
        record = result.trust_records[0]
        self.assertEqual(record.excluded_reason, "fx_missing")
        self.assertIsNone(record.base_amount)
        self.assertIsNone(record.fx_rate)
        self.assertIn("RECON_FX_MISSING", record.findings)
        # excluded amount must not affect total
        self.assertEqual(result.total_value_base, 0.0)

    def test_invariant_sum_matches_total_value_base(self) -> None:
        result = aggregate_portfolio(
            _portfolio(
                [
                    {
                        "id": "h1",
                        "asset_type_id": "stock",
                        "quantity": 1,
                        "market_value": {"amount": 100.0, "currency": "USD"},
                    },
                    {
                        "id": "h2",
                        "asset_type_id": "stock",
                        "quantity": 1,
                        "market_value": {"amount": 50.0, "currency": "EUR"},
                    },
                    {
                        "id": "h3",
                        "asset_type_id": "stock",
                        "quantity": 1,
                        "market_value": {"amount": 999.0, "currency": "GBP"},
                    },
                ]
            ),
            fx_rates_to_base={"EUR": 1.1},
        )

        included = sum(
            r.base_amount or 0.0
            for r in result.trust_records
            if r.excluded_reason is None
        )
        self.assertAlmostEqual(round(included, 2), result.total_value_base)
        excluded = [r for r in result.trust_records if r.excluded_reason == "fx_missing"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0].holding_id, "h3")


if __name__ == "__main__":
    unittest.main()
