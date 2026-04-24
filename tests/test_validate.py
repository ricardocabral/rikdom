from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from rikdom.storage import load_json
from rikdom.validate import validate_portfolio


class ValidateTests(unittest.TestCase):
    def test_example_portfolio_is_valid(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        errors = validate_portfolio(portfolio)
        self.assertEqual(errors, [])

    def test_operations_event_must_reference_existing_task(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        candidate["operations"]["task_events"][0]["task_id"] = "unknown-task"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("not in operations.task_catalog" in error for error in errors),
            msg=f"Expected task reference error, got: {errors}",
        )

    def test_operations_event_reference_rejected_with_empty_or_missing_catalog(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")

        for mutate_catalog in ("empty", "missing"):
            with self.subTest(catalog_state=mutate_catalog):
                candidate = copy.deepcopy(portfolio)
                candidate["operations"]["task_events"][0]["task_id"] = "unknown-task"

                if mutate_catalog == "empty":
                    candidate["operations"]["task_catalog"] = []
                else:
                    del candidate["operations"]["task_catalog"]

                errors = validate_portfolio(candidate)
                self.assertTrue(
                    any("not in operations.task_catalog" in error for error in errors),
                    msg=f"Expected task reference error with {mutate_catalog} catalog, got: {errors}",
                )

    def test_operations_last_event_must_exist(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        candidate["operations"]["task_catalog"][0]["last_event_id"] = "missing-event-id"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("last_event_id" in error and "not in operations.task_events" in error for error in errors),
            msg=f"Expected last_event_id integrity error, got: {errors}",
        )

    def test_missing_required_instrument_attribute_is_invalid(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        td_holding = next(h for h in candidate["holdings"] if h["id"] == "h-td-ipca")
        del td_holding["instrument_attributes"]["expiration_year"]

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("missing required key 'expiration_year'" in error for error in errors),
            msg=f"Expected required instrument attribute error, got: {errors}",
        )

    def test_instrument_attribute_is_rejected_when_asset_type_declares_none(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        stock_holding = next(h for h in candidate["holdings"] if h["asset_type_id"] == "stock")
        stock_holding["instrument_attributes"] = {"ticker": "PETR4"}

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any(
                "instrument_attributes.ticker not declared for asset_type_id 'stock'" in error
                for error in errors
            ),
            msg=f"Expected undeclared instrument attribute error, got: {errors}",
        )

    def test_major_version_mismatch_is_reported(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["schema_version"] = "2.0.0"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("schema_version '2.0.0' is incompatible" in e for e in errors),
            msg=f"Expected major mismatch error, got: {errors}",
        )

    def test_future_minor_version_is_reported(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["schema_version"] = "1.99.0"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("newer than current" in e for e in errors),
            msg=f"Expected future-version warning, got: {errors}",
        )

    def test_schema_version_below_minimum_is_reported(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["schema_version"] = "1.0.0"

        with patch("rikdom.validate.MIN_COMPATIBLE_SCHEMA_VERSION", (1, 1, 0)):
            errors = validate_portfolio(candidate)
        self.assertTrue(
            any("below minimum compatible" in e for e in errors),
            msg=f"Expected minimum-compatible error, got: {errors}",
        )

    def test_non_semver_schema_version_is_reported(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["schema_version"] = "v1"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("must be semantic version" in e for e in errors),
            msg=f"Expected semver format error, got: {errors}",
        )

    def test_non_canonical_schema_uri_is_reported(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["schema_uri"] = "https://example.org/other.json"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("does not match canonical" in e for e in errors),
            msg=f"Expected canonical uri error, got: {errors}",
        )

    def test_empty_schema_uri_is_reported_as_non_canonical(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["schema_uri"] = ""

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("does not match canonical" in e for e in errors),
            msg=f"Expected canonical uri error for empty string, got: {errors}",
        )

    def test_instrument_attribute_type_must_match_definition(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)

        td_holding = next(h for h in candidate["holdings"] if h["id"] == "h-td-ipca")
        td_holding["instrument_attributes"]["semestral_payments"] = "no"

        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("instrument_attributes.semestral_payments must be boolean" in error for error in errors),
            msg=f"Expected instrument attribute type error, got: {errors}",
        )


class EconomicExposureValidationTests(unittest.TestCase):
    def _portfolio_with_holding_exposure(self, breakdown: list[dict]) -> dict:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["holdings"][0]["economic_exposure"] = {
            "classification_source": "manual",
            "breakdown": breakdown,
        }
        return candidate

    def test_valid_multi_line_breakdown_summing_to_100_is_accepted(self) -> None:
        candidate = self._portfolio_with_holding_exposure([
            {"weight_pct": 62, "asset_class": "stocks"},
            {"weight_pct": 27, "asset_class": "stocks"},
            {"weight_pct": 11, "asset_class": "stocks"},
        ])
        errors = validate_portfolio(candidate)
        self.assertFalse(
            any("economic_exposure" in e for e in errors),
            msg=f"Did not expect exposure errors, got: {errors}",
        )

    def test_overweight_breakdown_is_rejected(self) -> None:
        candidate = self._portfolio_with_holding_exposure([
            {"weight_pct": 60, "asset_class": "stocks"},
            {"weight_pct": 60, "asset_class": "debt"},
        ])
        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("must sum to ~100" in e for e in errors),
            msg=f"Expected weight-sum error, got: {errors}",
        )

    def test_underweight_breakdown_is_rejected(self) -> None:
        candidate = self._portfolio_with_holding_exposure([
            {"weight_pct": 20, "asset_class": "stocks"},
        ])
        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("must sum to ~100" in e for e in errors),
            msg=f"Expected weight-sum error, got: {errors}",
        )

    def test_tolerance_band_accepts_small_rounding_residual(self) -> None:
        candidate = self._portfolio_with_holding_exposure([
            {"weight_pct": 33.3, "asset_class": "stocks"},
            {"weight_pct": 33.3, "asset_class": "debt"},
            {"weight_pct": 33.3, "asset_class": "cash_equivalents"},
        ])
        errors = validate_portfolio(candidate)
        self.assertFalse(
            any("economic_exposure" in e for e in errors),
            msg=f"Did not expect exposure errors within tolerance, got: {errors}",
        )

    def test_empty_breakdown_is_rejected(self) -> None:
        candidate = self._portfolio_with_holding_exposure([])
        errors = validate_portfolio(candidate)
        self.assertTrue(
            any("breakdown must be a non-empty array" in e for e in errors),
            msg=f"Expected empty-breakdown error, got: {errors}",
        )

    def test_asset_type_catalog_exposure_is_also_validated(self) -> None:
        portfolio = load_json("tests/fixtures/portfolio.json")
        candidate = copy.deepcopy(portfolio)
        candidate["asset_type_catalog"][0]["economic_exposure"] = {
            "breakdown": [
                {"weight_pct": 10, "asset_class": "stocks"},
            ],
        }
        errors = validate_portfolio(candidate)
        self.assertTrue(
            any(
                "asset_type_catalog[0].economic_exposure.breakdown" in e
                and "must sum to ~100" in e
                for e in errors
            ),
            msg=f"Expected catalog exposure error, got: {errors}",
        )


if __name__ == "__main__":
    unittest.main()
