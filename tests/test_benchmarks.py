from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.benchmarks import (
    BenchmarkPoint,
    benchmark_native_twr,
    load_benchmark_series,
    make_dir_loader,
    resolve_benchmarks_for_targets,
)


def _dt(s: str) -> datetime:
    text = s if not s.endswith("Z") else s[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


class LoadSeriesTests(unittest.TestCase):
    def test_skips_malformed_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "ibov.jsonl"
            _write_jsonl(
                p,
                [
                    {"as_of": "2026-01-31", "level": 100.0, "currency": "BRL"},
                    {"as_of": "bogus", "level": 200.0, "currency": "BRL"},
                    {"as_of": "2026-02-28", "level": -5.0, "currency": "BRL"},
                    {"as_of": "2026-03-31", "level": 110.0, "currency": "BR"},
                    {"as_of": "2026-02-28", "level": 105.0, "currency": "BRL"},
                ],
            )
            series = load_benchmark_series(p)
        self.assertEqual([p.level for p in series], [100.0, 105.0])
        self.assertTrue(all(p.currency == "BRL" for p in series))

    def test_sorted_chronologically(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.jsonl"
            _write_jsonl(
                p,
                [
                    {"as_of": "2026-03-31", "level": 110.0, "currency": "BRL"},
                    {"as_of": "2026-01-31", "level": 100.0, "currency": "BRL"},
                ],
            )
            series = load_benchmark_series(p)
        self.assertEqual([p.level for p in series], [100.0, 110.0])


class NativeTwrTests(unittest.TestCase):
    def test_simple_growth(self) -> None:
        series = [
            BenchmarkPoint(_dt("2026-01-31T23:59:59Z"), 100.0, "BRL"),
            BenchmarkPoint(_dt("2026-04-30T23:59:59Z"), 110.0, "BRL"),
        ]
        twr, warns = benchmark_native_twr(
            series,
            _dt("2026-01-31T23:59:59Z"),
            _dt("2026-04-30T23:59:59Z"),
        )
        assert twr is not None
        self.assertAlmostEqual(twr, 0.10, places=6)
        self.assertEqual(warns, [])

    def test_no_coverage_returns_none(self) -> None:
        series = [BenchmarkPoint(_dt("2026-05-01T00:00:00Z"), 100.0, "BRL")]
        twr, warns = benchmark_native_twr(
            series, _dt("2026-01-31T23:59:59Z"), _dt("2026-04-30T23:59:59Z")
        )
        self.assertIsNone(twr)
        self.assertTrue(any("no points" in w for w in warns))

    def test_picks_latest_at_or_before_bookends(self) -> None:
        series = [
            BenchmarkPoint(_dt("2026-01-15T23:59:59Z"), 90.0, "BRL"),
            BenchmarkPoint(_dt("2026-01-31T23:59:59Z"), 100.0, "BRL"),
            BenchmarkPoint(_dt("2026-02-28T23:59:59Z"), 105.0, "BRL"),
            BenchmarkPoint(_dt("2026-04-19T23:59:59Z"), 110.0, "BRL"),
            BenchmarkPoint(_dt("2026-04-30T23:59:59Z"), 115.0, "BRL"),
        ]
        twr, _ = benchmark_native_twr(
            series, _dt("2026-01-31T23:59:59Z"), _dt("2026-04-19T23:59:59Z")
        )
        assert twr is not None
        self.assertAlmostEqual(twr, 0.10, places=6)


class ResolveTests(unittest.TestCase):
    POLICY = {
        "benchmarks": [
            {"id": "ibov", "label": "Ibovespa", "kind": "index", "currency": "BRL"},
            {"id": "sp500", "label": "S&P 500", "kind": "index", "currency": "USD"},
            {
                "id": "blend",
                "label": "Blend",
                "kind": "composite",
                "currency": "BRL",
                "components": [
                    {"benchmark_id": "ibov", "weight_pct": 60},
                    {"benchmark_id": "sp500", "weight_pct": 40},
                ],
            },
            {
                "id": "missing-series",
                "label": "Missing",
                "kind": "index",
                "currency": "BRL",
            },
        ],
        "strategic_allocation": {
            "targets": [
                {"dimension": "asset_class", "bucket": "stocks", "weight_pct": 70, "benchmark_id": "blend"},
                {"dimension": "asset_class", "bucket": "cash", "weight_pct": 30, "benchmark_id": "missing-series"},
            ],
        },
    }

    def _write_dir(self, tmp: Path) -> Path:
        bench_dir = tmp / "benchmarks"
        bench_dir.mkdir()
        _write_jsonl(
            bench_dir / "ibov.jsonl",
            [
                {"as_of": "2026-01-31", "level": 100.0, "currency": "BRL"},
                {"as_of": "2026-04-19", "level": 110.0, "currency": "BRL"},
            ],
        )
        _write_jsonl(
            bench_dir / "sp500.jsonl",
            [
                {"as_of": "2026-01-31", "level": 4800.0, "currency": "USD"},
                {"as_of": "2026-04-19", "level": 5040.0, "currency": "USD"},
            ],
        )
        return bench_dir

    def test_composite_blends_native_twrs_and_warns_on_currency_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            bench_dir = self._write_dir(Path(tmp))
            loader = make_dir_loader(bench_dir)
            results = resolve_benchmarks_for_targets(
                self.POLICY,
                loader,
                _dt("2026-01-31T23:59:59Z"),
                _dt("2026-04-19T23:59:59Z"),
                base_currency="BRL",
                period_start_iso="2026-01-31T23:59:59Z",
                period_end_iso="2026-04-19T23:59:59Z",
                portfolio_twr_pct=12.0,
            )
        by_id = {r.benchmark_id: r for r in results}
        self.assertEqual(set(by_id), {"blend", "missing-series"})

        blend = by_id["blend"]
        # 0.6 * 10% + 0.4 * 5% = 8% (native TWRs blended).
        assert blend.twr_pct is not None
        self.assertAlmostEqual(blend.twr_pct, 8.0, places=4)
        self.assertAlmostEqual(blend.excess_pct or 0.0, 12.0 - 8.0, places=4)
        self.assertTrue(any("USD" in w for w in blend.warnings))
        self.assertEqual(len(blend.components), 2)

    def test_missing_series_emits_warning_no_crash(self) -> None:
        with TemporaryDirectory() as tmp:
            bench_dir = self._write_dir(Path(tmp))
            loader = make_dir_loader(bench_dir)
            results = resolve_benchmarks_for_targets(
                self.POLICY,
                loader,
                _dt("2026-01-31T23:59:59Z"),
                _dt("2026-04-19T23:59:59Z"),
                base_currency="BRL",
                period_start_iso="2026-01-31T23:59:59Z",
                period_end_iso="2026-04-19T23:59:59Z",
                portfolio_twr_pct=None,
            )
        missing = next(r for r in results if r.benchmark_id == "missing-series")
        self.assertIsNone(missing.twr_pct)
        self.assertTrue(any("series file" in w for w in missing.warnings))

    def test_composite_cycle_short_circuits(self) -> None:
        policy = {
            "benchmarks": [
                {
                    "id": "a",
                    "label": "A",
                    "kind": "composite",
                    "currency": "BRL",
                    "components": [{"benchmark_id": "b", "weight_pct": 100}],
                },
                {
                    "id": "b",
                    "label": "B",
                    "kind": "composite",
                    "currency": "BRL",
                    "components": [{"benchmark_id": "a", "weight_pct": 100}],
                },
            ],
            "strategic_allocation": {
                "targets": [
                    {"dimension": "asset_class", "bucket": "x", "weight_pct": 100, "benchmark_id": "a"},
                ],
            },
        }
        with TemporaryDirectory() as tmp:
            loader = make_dir_loader(Path(tmp))
            results = resolve_benchmarks_for_targets(
                policy,
                loader,
                _dt("2026-01-01T00:00:00Z"),
                _dt("2026-04-01T00:00:00Z"),
                base_currency="BRL",
                period_start_iso="2026-01-01T00:00:00Z",
                period_end_iso="2026-04-01T00:00:00Z",
                portfolio_twr_pct=5.0,
            )
        self.assertEqual(len(results), 1)
        a = results[0]
        # Cycle is reported on the inner component, not the outer composite.
        def collect(node, acc):
            acc.extend(node.warnings)
            for c in node.components:
                collect(c, acc)
        cycle_msgs: list[str] = []
        collect(a, cycle_msgs)
        self.assertTrue(any("cycle" in w.lower() for w in cycle_msgs))


if __name__ == "__main__":
    unittest.main()
