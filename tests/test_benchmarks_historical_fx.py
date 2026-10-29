"""Independent benchmark contract tests; real FX integration lives in CLI tests."""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from rikdom.benchmarks import (
    BenchmarkPoint,
    benchmark_native_twr,
    load_benchmark_series,
    resolve_benchmarks_for_targets,
)

START = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
END = datetime(2026, 4, 30, 23, 59, 59, tzinfo=timezone.utc)


@dataclass(frozen=True)
class RateResult:
    rate: float | None
    status: str
    reason: str | None
    evidence: dict[str, Any]


class DatedRates:
    """Contract double while HistoricalFx is built in a separate worktree."""

    base_currency = "BRL"

    def __init__(self, rates=None):
        self.rates = (
            rates
            if rates is not None
            else {
                ("USD", START): RateResult(
                    5.0, "available", None, {"revision": "initial"}
                ),
                ("USD", END): RateResult(
                    6.0, "available", None, {"revision": "corrected"}
                ),
            }
        )

    def resolve(self, currency, when):
        if currency == self.base_currency:
            return RateResult(1.0, "available", None, {"identity": True})
        return self.rates.get(
            (currency, when), RateResult(None, "unavailable", "missing_mapping", {})
        )


def points(currency="USD", convention="total_return", source="synthetic-index"):
    return [
        BenchmarkPoint(START, 100.0, currency, convention, source),
        BenchmarkPoint(END, 110.0, currency, convention, source),
    ]


def policy(components=None):
    benches = [
        {"id": "usd", "kind": "index", "currency": "USD"},
        {"id": "brl", "kind": "index", "currency": "BRL"},
    ]
    target = "usd"
    if components is not None:
        target = "blend"
        benches.append(
            {
                "id": target,
                "kind": "composite",
                "currency": "BRL",
                "components": components,
            }
        )
    return {
        "benchmarks": benches,
        "strategic_allocation": {"targets": [{"benchmark_id": target}]},
    }


def compare(series=None, *, config=None, fx=None, start=START, end=END, portfolio=20.0):
    lookup = {"usd": points(), "brl": points("BRL")} if series is None else series
    return resolve_benchmarks_for_targets(
        policy() if config is None else config,
        lambda bid: lookup.get(bid, []),
        start,
        end,
        "BRL",
        start.isoformat(),
        end.isoformat(),
        portfolio,
        historical_fx=DatedRates() if fx is None else fx,
    )[0]


class HistoricalBenchmarkTests(unittest.TestCase):
    def test_converts_both_bookends_and_preserves_rate_vintages(self):
        result = compare()
        self.assertEqual(result.currency, "BRL")
        self.assertEqual(result.native_currency, "USD")
        self.assertEqual(result.native_twr_pct, 10.0)
        # 110 USD * 6 / (100 USD * 5) - 1 = 32% BRL.
        self.assertEqual(result.twr_pct, 32.0)
        self.assertEqual(result.excess_pct, -12.0)
        self.assertEqual(result.comparison_status, "comparable")
        self.assertEqual(result.return_convention, "total_return")
        self.assertEqual(
            [r["evidence"]["revision"] for r in result.fx_evidence],
            ["initial", "corrected"],
        )
        self.assertEqual(
            [r["source"] for r in result.data_provenance],
            ["synthetic-index", "synthetic-index"],
        )
        self.assertEqual(result.data_provenance[0]["as_of"], START.isoformat())
        self.assertTrue(
            any(
                "snapshot" in w.lower() and "total-return" in w.lower()
                for w in result.warnings
            )
        )

    def test_native_identity_has_no_fx_drift(self):
        result = compare(
            {"usd": points("BRL")},
            config={
                "benchmarks": [{"id": "usd", "kind": "index", "currency": "BRL"}],
                "strategic_allocation": {"targets": [{"benchmark_id": "usd"}]},
            },
        )
        self.assertEqual(result.twr_pct, 10.0)
        self.assertEqual(result.excess_pct, 10.0)
        self.assertEqual([r["rate"] for r in result.fx_evidence], [1.0, 1.0])

    def test_composite_blends_reporting_currency_returns(self):
        result = compare(
            config=policy(
                [
                    {"benchmark_id": "brl", "weight_pct": 60},
                    {"benchmark_id": "usd", "weight_pct": 40},
                ]
            )
        )
        self.assertEqual(result.twr_pct, 18.8)
        self.assertEqual(result.excess_pct, 1.2)
        self.assertEqual([c.currency for c in result.components], ["BRL", "BRL"])
        self.assertEqual(result.comparison_status, "comparable")
        self.assertEqual(len(result.fx_evidence), 4)
        self.assertTrue(
            any(
                "snapshot" in w.lower() and "total-return" in w.lower()
                for w in result.warnings
            )
        )

    def test_missing_stale_or_wrong_pair_prevents_return_without_fallback(self):
        for reason in ("missing_mapping", "stale", "incompatible_pair"):
            with self.subTest(reason=reason):
                fx = DatedRates(
                    {
                        ("USD", START): RateResult(5.0, "available", None, {}),
                        ("USD", END): RateResult(
                            None, "unavailable", reason, {"status": reason}
                        ),
                    }
                )
                result = compare(fx=fx)
                self.assertIsNone(result.twr_pct)
                self.assertIsNone(result.excess_pct)
                self.assertEqual(result.native_twr_pct, 10.0)
                self.assertEqual(result.comparison_status, "unavailable")
                self.assertEqual(result.fx_evidence[-1]["reason"], reason)
                self.assertTrue(any(reason in w for w in result.warnings))

    def test_invalid_rates_or_overflow_do_not_escape_as_nonfinite_returns(self):
        for rate in (True, 0, -1, float("nan"), float("inf"), 1e308):
            with self.subTest(rate=rate):
                result = compare(
                    fx=DatedRates(
                        {
                            ("USD", START): RateResult(5.0, "available", None, {}),
                            ("USD", END): RateResult(rate, "available", None, {}),
                        }
                    )
                )
                self.assertIsNone(result.twr_pct)
                self.assertIsNone(result.excess_pct)

    def test_actual_dates_drive_fx_and_prevent_mismatched_window_excess(self):
        prior = START - timedelta(days=1)
        fx = DatedRates(
            {
                ("USD", prior): RateResult(5.0, "available", None, {}),
                ("USD", END): RateResult(6.0, "available", None, {}),
            }
        )
        result = compare(
            {
                "usd": [
                    BenchmarkPoint(prior, 100, "USD", "total_return", "source"),
                    points()[1],
                ]
            },
            fx=fx,
        )
        self.assertEqual(result.twr_pct, 32.0)
        self.assertIsNone(result.excess_pct)
        self.assertEqual(result.comparison_status, "not_comparable")
        self.assertEqual(result.period_start, prior.isoformat())
        self.assertTrue(any("window" in w.lower() for w in result.warnings))

    def test_unknown_price_or_inconsistent_conventions_show_return_without_excess(self):
        for convention in ("unspecified", "price_return", "price_only"):
            with self.subTest(convention=convention):
                result = compare({"usd": points(convention=convention)})
                self.assertEqual(result.twr_pct, 32.0)
                self.assertIsNone(result.excess_pct)
                self.assertEqual(result.comparison_status, "not_comparable")
                self.assertTrue(any("convention" in w.lower() for w in result.warnings))
        series = points()
        series[1] = BenchmarkPoint(END, 110, "USD", "price_return", "synthetic-index")
        self.assertIsNone(compare({"usd": series}).excess_pct)

    def test_missing_source_prevents_excess_but_retains_converted_return(self):
        for source in (None, "", "   "):
            with self.subTest(source=source):
                result = compare({"usd": points(source=source)})
                self.assertEqual(result.twr_pct, 32.0)
                self.assertIsNone(result.excess_pct)
                self.assertTrue(any("source" in w.lower() for w in result.warnings))

    def test_partial_composite_is_unavailable_and_not_renormalized(self):
        result = compare(
            {"brl": points("BRL")},
            config=policy(
                [
                    {"benchmark_id": "brl", "weight_pct": 60},
                    {"benchmark_id": "usd", "weight_pct": 40},
                ]
            ),
        )
        self.assertIsNone(result.twr_pct)
        self.assertIsNone(result.excess_pct)
        self.assertEqual(result.comparison_status, "unavailable")

    def test_zero_weight_missing_component_can_be_ignored(self):
        result = compare(
            config=policy(
                [
                    {"benchmark_id": "usd", "weight_pct": 100},
                    {"benchmark_id": "missing", "weight_pct": 0},
                ]
            )
        )
        self.assertEqual(result.twr_pct, 32.0)
        self.assertEqual(result.excess_pct, -12.0)

    def test_all_positive_components_must_be_comparable_for_composite_excess(self):
        result = compare(
            {"usd": points(), "brl": points("BRL", "price_return")},
            config=policy(
                [
                    {"benchmark_id": "usd", "weight_pct": 50},
                    {"benchmark_id": "brl", "weight_pct": 50},
                ]
            ),
        )
        self.assertEqual(result.twr_pct, 21.0)
        self.assertIsNone(result.excess_pct)
        self.assertEqual(result.comparison_status, "not_comparable")

    def test_invalid_weights_fail_closed(self):
        for weight in (True, float("nan"), float("inf"), -1, 0, 99.9, 100.1, "100"):
            with self.subTest(weight=weight):
                result = compare(
                    config=policy([{"benchmark_id": "usd", "weight_pct": weight}])
                )
                self.assertIsNone(result.twr_pct)
                self.assertIsNone(result.excess_pct)
                self.assertEqual(result.comparison_status, "unavailable")
        result = compare(
            config=policy([{"benchmark_id": "usd", "weight_pct": 100.0000005}])
        )
        self.assertAlmostEqual(result.twr_pct, 32.0, places=5)

    def test_invalid_extra_component_cannot_be_silently_skipped(self):
        for component in (None, {}, {"benchmark_id": "usd"}, {"weight_pct": 0}):
            with self.subTest(component=component):
                result = compare(
                    config=policy(
                        [{"benchmark_id": "usd", "weight_pct": 100}, component]
                    )
                )
                self.assertIsNone(result.twr_pct)

    def test_cycle_and_duplicate_bookend_dates_are_unavailable(self):
        cyclic = policy([{"benchmark_id": "blend", "weight_pct": 100}])
        self.assertIsNone(compare(config=cyclic).twr_pct)
        self.assertIsNone(compare({"usd": points() + [points()[0]]}).twr_pct)

    def test_naive_or_reversed_window_is_rejected(self):
        for start, end in (
            (START.replace(tzinfo=None), END),
            (END, START),
            (START, START),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                compare(start=start, end=end)

    def test_resolver_reporting_currency_must_match_portfolio(self):
        fx = DatedRates()
        fx.base_currency = "EUR"
        with self.assertRaises(ValueError):
            compare(fx=fx)

    def test_nonfinite_portfolio_return_does_not_create_excess(self):
        for value in (True, float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(compare(portfolio=value).excess_pct)


class BenchmarkInputSafetyTests(unittest.TestCase):
    def test_loader_reads_optional_metadata_and_skips_nonfinite_levels(self):
        rows = [
            {
                "as_of": "2026-01-31",
                "level": 100,
                "currency": "USD",
                "return_convention": "total_return",
                "source": "synthetic-index",
            },
            {"as_of": "2026-02-28", "level": float("nan"), "currency": "USD"},
            {"as_of": "2026-03-31", "level": float("inf"), "currency": "USD"},
            {"as_of": "2026-04-30", "level": 110, "currency": "USD"},
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "series.jsonl"
            path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )
            loaded = load_benchmark_series(path)
        self.assertEqual([p.level for p in loaded], [100, 110])
        self.assertEqual(loaded[0].return_convention, "total_return")
        self.assertEqual(loaded[0].source, "synthetic-index")
        self.assertEqual(loaded[1].return_convention, "unspecified")
        self.assertIsNone(loaded[1].source)

    def test_native_and_historical_paths_reject_invalid_bookend_levels(self):
        for level in (True, 0, -1, float("nan"), float("inf"), 1e-308):
            with self.subTest(level=level):
                series = [
                    BenchmarkPoint(START, level, "USD"),
                    BenchmarkPoint(END, 1e308, "USD"),
                ]
                value, warnings = benchmark_native_twr(series, START, END)
                self.assertIsNone(value)
                self.assertTrue(warnings)
                result = compare({"usd": series})
                self.assertIsNone(result.twr_pct)
                json.dumps(asdict(result), allow_nan=False)

    def test_loader_preserves_naive_date_ambiguity_for_historical_rejection(self):
        rows = [
            {
                "as_of": "2026-01-31T23:59:59",
                "level": 100,
                "currency": "USD",
                "return_convention": "total_return",
                "source": "source",
            },
            {
                "as_of": END.isoformat(),
                "level": 110,
                "currency": "USD",
                "return_convention": "total_return",
                "source": "source",
            },
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "series.jsonl"
            path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )
            loaded = load_benchmark_series(path)
        # Legacy timestamps remain interpreted as UTC for compatibility.
        legacy = resolve_benchmarks_for_targets(
            policy(),
            lambda _: loaded,
            START,
            END,
            "BRL",
            START.isoformat(),
            END.isoformat(),
            20,
        )[0]
        self.assertEqual(legacy.twr_pct, 10.0)
        historical = compare({"usd": loaded})
        self.assertIsNone(historical.twr_pct)
        self.assertTrue(any("ambiguous" in w.lower() for w in historical.warnings))

    def test_legacy_foreign_output_stays_native(self):
        result = resolve_benchmarks_for_targets(
            policy(),
            lambda _: points(),
            START,
            END,
            "BRL",
            START.isoformat(),
            END.isoformat(),
            20,
        )[0]
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.twr_pct, 10.0)
        self.assertIsNone(result.excess_pct)

class RealResolverCurrencyValidationTests(unittest.TestCase):
    def test_invalid_direct_bookend_currency_is_unavailable(self):
        from rikdom.historical_fx import HistoricalFx
        from rikdom.market_series import load_market_series
        from tests.test_historical_fx import fx_document

        config = {'benchmarks': [{'id': 'invalid', 'kind': 'index'}],
                  'strategic_allocation': {'targets': [{'benchmark_id': 'invalid'}]}}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'series.json'
            path.write_text(json.dumps(fx_document()))
            fx = HistoricalFx(load_market_series(path), base_currency='BRL',
                              series_by_currency={'USD': 'usd-brl'}, max_age_seconds=0)
            for currency in ('US$', 'usd', 'ＵＳＤ', '', None):
                with self.subTest(currency=currency):
                    result = resolve_benchmarks_for_targets(
                        config, lambda _: points(currency), START, END, 'BRL',
                        START.isoformat(), END.isoformat(), 20, historical_fx=fx)[0]
                    self.assertEqual(result.comparison_status, 'unavailable')
                    self.assertIsNone(result.twr_pct)
                    self.assertIsNone(result.excess_pct)
                    self.assertTrue(any('currency' in warning.lower() for warning in result.warnings))
