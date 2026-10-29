"""Portfolio benchmark excess requires explicit bookend conventions."""
import copy
from pathlib import Path
import unittest

from rikdom.benchmarks import BenchmarkPoint
from rikdom.historical_fx import load_historical_fx
from rikdom.performance import compute_performance, performance_result_to_dict
from rikdom.performance_report import performance_to_dict
from datetime import datetime

START = "2026-01-01T00:00:00Z"
END = "2027-01-01T00:00:00Z"


def snapshots():
    return [{"timestamp": stamp, "base_currency": "BRL", "totals": {"portfolio_value_base": value}}
            for stamp, value in ((START, 100), (END, 121))]


def declare(rows, kind="total_return", source="manual:reviewed-full-nav"):
    for row in rows:
        row["metadata"] = {"rikdom_return_convention": {"version": 1, "kind": kind, "source": source}}
    return rows


def calculate(rows):
    fx = load_historical_fx(Path("data-sample/performance-fx/historical-fx.json"), base_currency="BRL")
    points = [BenchmarkPoint(datetime.fromisoformat(stamp.replace("Z", "+00:00")), level,
                             "USD", "total_return", "synthetic:total-return-index")
              for stamp, level in ((START, 100), (END, 110))]
    policy = {"benchmarks": [{"id": "foreign", "kind": "index", "currency": "USD"}],
              "strategic_allocation": {"targets": [{"benchmark_id": "foreign"}]}}
    return compute_performance(rows, [], base_currency="BRL", historical_fx=fx,
                               policy=policy, benchmark_loader=lambda _: points)


class PerformanceConventionTests(unittest.TestCase):
    def test_unknown_portfolio_convention_keeps_benchmark_return_but_not_excess(self):
        output = performance_to_dict(calculate(snapshots()))
        comparison = output["benchmarks"][0]
        self.assertEqual(comparison["twr_pct"], 32)
        self.assertIsNone(comparison["excess_pct"])
        self.assertEqual(comparison["comparison_status"], "not_comparable")
        self.assertEqual(output["return_convention"], "unspecified")

    def test_reviewed_total_return_supports_same_currency_period_excess(self):
        output = performance_to_dict(calculate(declare(snapshots())))
        comparison = output["benchmarks"][0]
        self.assertEqual(comparison["comparison_status"], "comparable")
        self.assertEqual(comparison["excess_pct"], -11)
        self.assertEqual(output["return_convention"], "total_return")
        self.assertEqual(len(output["return_convention_evidence"]), 2)

    def test_price_or_mismatched_or_invalid_convention_never_claims_comparability(self):
        for value in ("price_return", "unknown", None, True):
            with self.subTest(kind=value):
                rows = declare(snapshots(), kind=value)
                comparison = calculate(rows).benchmarks[0]
                self.assertIsNone(comparison.excess_pct)
                self.assertEqual(comparison.comparison_status, "not_comparable")
        rows = declare(snapshots())
        rows[1]["metadata"]["rikdom_return_convention"]["kind"] = "price_return"
        self.assertIsNone(calculate(rows).benchmarks[0].excess_pct)

    def test_missing_source_unknown_version_and_extra_fields_fail_closed(self):
        for change in ({"source": ""}, {"source": None}, {"version": True}, {"version": 2}, {"extra": 1}):
            with self.subTest(change=change):
                rows = declare(snapshots())
                rows[0]["metadata"]["rikdom_return_convention"].update(change)
                self.assertIsNone(calculate(rows).benchmarks[0].excess_pct)

    def test_serialized_convention_evidence_is_detached_and_inputs_unchanged(self):
        rows = declare(snapshots())
        before = copy.deepcopy(rows)
        result = calculate(rows)
        output = performance_result_to_dict(result)
        output["return_convention_evidence"][0]["source"] = "changed"
        self.assertEqual(rows, before)
        self.assertEqual(result.return_convention_evidence[0]["source"], "manual:reviewed-full-nav")
