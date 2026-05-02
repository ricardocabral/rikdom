"""Benchmark series loading and TWR computation.

Benchmarks are stored as one JSONL file per ``benchmark_id`` under a
benchmarks directory (default: ``data/benchmarks``). Each row carries an
``as_of`` date, a ``level`` (index value in arbitrary units — only ratios
matter), and a ``currency``. Composite benchmarks defined in policy are
resolved as a weighted blend of component TWRs.

Scope: this module computes per-benchmark TWR over the same window used
for portfolio TWR/MWR and reports excess return when currencies match.
FX-translation of foreign-currency benchmark levels into base currency is
deliberately out of scope for the no-schema-bump MVP — for those, the
benchmark return is reported in its native currency and ``excess_pct`` is
left ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .storage import load_jsonl


@dataclass(frozen=True)
class BenchmarkPoint:
    as_of: datetime
    level: float
    currency: str


@dataclass
class BenchmarkComparison:
    benchmark_id: str
    label: str
    kind: str
    currency: str
    twr_pct: float | None
    excess_pct: float | None
    period_start: str
    period_end: str
    warnings: list[str] = field(default_factory=list)
    components: list["BenchmarkComparison"] = field(default_factory=list)


def _parse_as_of(value: str) -> datetime:
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        # Pure date — anchor at end-of-day UTC so comparisons against a
        # period_end that is itself end-of-day work the way callers expect.
        return datetime.fromisoformat(text + "T23:59:59+00:00")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_benchmark_series(path: str | Path) -> list[BenchmarkPoint]:
    """Read ``<benchmarks_dir>/<id>.jsonl`` and return sorted points.

    Malformed rows are skipped silently — the caller decides whether to
    surface a warning based on whether the resulting series is empty.
    """

    rows = load_jsonl(path)
    points: list[BenchmarkPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        as_of = row.get("as_of")
        level = row.get("level")
        currency = row.get("currency")
        if not isinstance(as_of, str):
            continue
        if not isinstance(level, (int, float)) or isinstance(level, bool):
            continue
        if level <= 0:
            continue
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            continue
        try:
            when = _parse_as_of(as_of)
        except ValueError:
            continue
        points.append(
            BenchmarkPoint(
                as_of=when,
                level=float(level),
                currency=currency.strip().upper(),
            )
        )
    points.sort(key=lambda p: p.as_of)
    return points


def _select_bookends(
    series: list[BenchmarkPoint],
    period_start: datetime,
    period_end: datetime,
) -> tuple[BenchmarkPoint | None, BenchmarkPoint | None]:
    if not series:
        return None, None
    start: BenchmarkPoint | None = None
    for p in reversed(series):
        if p.as_of <= period_start:
            start = p
            break
    if start is None:
        # No point at-or-before period_start; fall back to the earliest
        # point inside the window so a partial answer is still possible.
        for p in series:
            if p.as_of >= period_start:
                start = p
                break
    end: BenchmarkPoint | None = None
    for p in reversed(series):
        if p.as_of <= period_end:
            end = p
            break
    return start, end


def benchmark_native_twr(
    series: list[BenchmarkPoint],
    period_start: datetime,
    period_end: datetime,
) -> tuple[float | None, list[str]]:
    """Return TWR fraction over the window in the benchmark's native currency."""

    warnings: list[str] = []
    start, end = _select_bookends(series, period_start, period_end)
    if start is None or end is None:
        warnings.append("Benchmark series has no points covering the window")
        return None, warnings
    if start.currency != end.currency:
        warnings.append(
            f"Benchmark currency changed within window ({start.currency} -> {end.currency})"
        )
        return None, warnings
    if start.as_of >= end.as_of:
        warnings.append("Benchmark bookends collapse to a single point")
        return None, warnings
    if start.level <= 0:
        return None, warnings
    return (end.level / start.level) - 1.0, warnings


BenchmarkLoader = Callable[[str], list[BenchmarkPoint]]


def make_dir_loader(benchmarks_dir: str | Path) -> BenchmarkLoader:
    """Default loader: ``<benchmarks_dir>/<id>.jsonl``."""

    base = Path(benchmarks_dir)

    def _load(benchmark_id: str) -> list[BenchmarkPoint]:
        path = base / f"{benchmark_id}.jsonl"
        if not path.exists():
            return []
        return load_benchmark_series(path)

    return _load


def _index_benchmarks(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for bench in policy.get("benchmarks") or []:
        if not isinstance(bench, dict):
            continue
        bid = bench.get("id")
        if isinstance(bid, str) and bid:
            out[bid] = bench
    return out


def _resolve_one(
    benchmark_id: str,
    benchmarks: dict[str, dict[str, Any]],
    loader: BenchmarkLoader,
    period_start: datetime,
    period_end: datetime,
    base_currency: str,
    period_start_iso: str,
    period_end_iso: str,
    *,
    visited: frozenset[str] = frozenset(),
) -> BenchmarkComparison:
    bench = benchmarks.get(benchmark_id)
    if bench is None:
        return BenchmarkComparison(
            benchmark_id=benchmark_id,
            label=benchmark_id,
            kind="unknown",
            currency="",
            twr_pct=None,
            excess_pct=None,
            period_start=period_start_iso,
            period_end=period_end_iso,
            warnings=[f"Benchmark '{benchmark_id}' not declared in policy"],
        )
    if benchmark_id in visited:
        return BenchmarkComparison(
            benchmark_id=benchmark_id,
            label=str(bench.get("label") or benchmark_id),
            kind=str(bench.get("kind") or "unknown"),
            currency=str(bench.get("currency") or ""),
            twr_pct=None,
            excess_pct=None,
            period_start=period_start_iso,
            period_end=period_end_iso,
            warnings=[f"Composite cycle detected at '{benchmark_id}'"],
        )

    label = str(bench.get("label") or benchmark_id)
    kind = str(bench.get("kind") or "unknown")
    currency = str(bench.get("currency") or "").strip().upper()

    if kind == "composite":
        return _resolve_composite(
            bench,
            benchmarks,
            loader,
            period_start,
            period_end,
            base_currency,
            period_start_iso,
            period_end_iso,
            label=label,
            currency=currency,
            visited=visited | {benchmark_id},
        )

    series = loader(benchmark_id)
    warnings: list[str] = []
    if not series:
        warnings.append(
            f"Benchmark '{benchmark_id}' has no series file (expected "
            f"<benchmarks-dir>/{benchmark_id}.jsonl)"
        )
        return BenchmarkComparison(
            benchmark_id=benchmark_id,
            label=label,
            kind=kind,
            currency=currency,
            twr_pct=None,
            excess_pct=None,
            period_start=period_start_iso,
            period_end=period_end_iso,
            warnings=warnings,
        )

    series_currency = series[0].currency
    if currency and series_currency != currency:
        warnings.append(
            f"Benchmark '{benchmark_id}' series currency {series_currency} "
            f"does not match declared currency {currency}"
        )

    twr_fraction, native_warnings = benchmark_native_twr(
        series, period_start, period_end
    )
    warnings.extend(native_warnings)

    effective_currency = series_currency or currency
    return BenchmarkComparison(
        benchmark_id=benchmark_id,
        label=label,
        kind=kind,
        currency=effective_currency,
        twr_pct=None if twr_fraction is None else round(twr_fraction * 100, 6),
        excess_pct=None,
        period_start=period_start_iso,
        period_end=period_end_iso,
        warnings=warnings,
    )


def _resolve_composite(
    bench: dict[str, Any],
    benchmarks: dict[str, dict[str, Any]],
    loader: BenchmarkLoader,
    period_start: datetime,
    period_end: datetime,
    base_currency: str,
    period_start_iso: str,
    period_end_iso: str,
    *,
    label: str,
    currency: str,
    visited: frozenset[str],
) -> BenchmarkComparison:
    components_raw = bench.get("components") or []
    component_results: list[BenchmarkComparison] = []
    weights: list[tuple[BenchmarkComparison, float]] = []
    warnings: list[str] = []
    total_weight = 0.0

    for comp in components_raw:
        if not isinstance(comp, dict):
            continue
        ref = comp.get("benchmark_id")
        weight = comp.get("weight_pct")
        if not isinstance(ref, str) or not ref:
            continue
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            continue
        sub = _resolve_one(
            ref,
            benchmarks,
            loader,
            period_start,
            period_end,
            base_currency,
            period_start_iso,
            period_end_iso,
            visited=visited,
        )
        component_results.append(sub)
        weights.append((sub, float(weight)))
        total_weight += float(weight)

    if currency:
        mismatched = sorted(
            {
                sub.currency
                for sub, _ in weights
                if sub.currency and sub.currency.upper() != currency.upper()
            }
        )
        if mismatched:
            warnings.append(
                f"Composite components use {mismatched} but composite currency is "
                f"{currency}; native-currency TWRs blended without FX translation"
            )

    blended: float | None = None
    if total_weight > 0:
        agg = 0.0
        usable_weight = 0.0
        for sub, w in weights:
            if sub.twr_pct is None:
                warnings.append(
                    f"Composite component '{sub.benchmark_id}' has no return; "
                    f"weight {w} excluded"
                )
                continue
            agg += (sub.twr_pct / 100.0) * w
            usable_weight += w
        if usable_weight > 0:
            blended = (agg / usable_weight) * 100.0
            blended = round(blended, 6)
            if usable_weight < total_weight:
                warnings.append(
                    f"Composite blended over {usable_weight}/{total_weight} of "
                    "declared weight; result is partial"
                )

    return BenchmarkComparison(
        benchmark_id=str(bench.get("id") or ""),
        label=label,
        kind="composite",
        currency=currency,
        twr_pct=blended,
        excess_pct=None,
        period_start=period_start_iso,
        period_end=period_end_iso,
        warnings=warnings,
        components=component_results,
    )


def resolve_benchmarks_for_targets(
    policy: dict[str, Any],
    loader: BenchmarkLoader,
    period_start: datetime,
    period_end: datetime,
    base_currency: str,
    period_start_iso: str,
    period_end_iso: str,
    portfolio_twr_pct: float | None,
) -> list[BenchmarkComparison]:
    """Resolve every distinct benchmark referenced by strategic_allocation.

    Excess return (``excess_pct``) is computed only when the benchmark's
    currency matches ``base_currency`` and a portfolio TWR is available.
    """

    benchmarks = _index_benchmarks(policy)
    strat = policy.get("strategic_allocation")
    if not isinstance(strat, dict):
        return []
    targets = strat.get("targets") or []

    seen: set[str] = set()
    ordered_ids: list[str] = []
    for tgt in targets:
        if not isinstance(tgt, dict):
            continue
        bid = tgt.get("benchmark_id")
        if isinstance(bid, str) and bid and bid not in seen:
            seen.add(bid)
            ordered_ids.append(bid)

    base = base_currency.strip().upper()
    results: list[BenchmarkComparison] = []
    for bid in ordered_ids:
        comp = _resolve_one(
            bid,
            benchmarks,
            loader,
            period_start,
            period_end,
            base,
            period_start_iso,
            period_end_iso,
        )
        if (
            comp.twr_pct is not None
            and portfolio_twr_pct is not None
            and comp.currency
            and comp.currency.upper() == base
        ):
            comp.excess_pct = round(portfolio_twr_pct - comp.twr_pct, 6)
        elif comp.twr_pct is not None and comp.currency and comp.currency.upper() != base:
            comp.warnings.append(
                f"Benchmark currency {comp.currency} != base {base}; excess "
                "return not computed (FX translation deferred)"
            )
        results.append(comp)
    return results
