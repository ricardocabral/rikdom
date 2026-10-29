"""Benchmark series loading and TWR computation.

Benchmarks are stored as one JSONL file per ``benchmark_id`` under a
benchmarks directory (default: ``data/benchmarks``). Each row carries an
``as_of`` date, a ``level`` (index value in arbitrary units — only ratios
matter), and a ``currency``. Composite benchmarks defined in policy are
resolved as a weighted blend of component TWRs.

Scope: this module computes per-benchmark TWR over the same window used
for portfolio TWR/MWR and reports excess return when currencies match.
Without historical FX, foreign benchmarks retain their native returns.
With historical FX, bookends are translated independently into the reporting
currency and excess requires exact dates and sourced total-return levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import math
import re
from typing import TYPE_CHECKING, Any, Callable

from .storage import load_jsonl

if TYPE_CHECKING:
    from .historical_fx import HistoricalFx


@dataclass(frozen=True)
class BenchmarkPoint:
    as_of: datetime
    level: float
    currency: str
    return_convention: str = "unspecified"
    source: str | None = None
    # Keep the legacy UTC interpretation visible to strict historical callers.
    as_of_timezone_assumed: bool = False


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
    native_currency: str | None = None
    native_twr_pct: float | None = None
    return_convention: str = "unspecified"
    fx_evidence: list[dict[str, Any]] = field(default_factory=list)
    data_provenance: list[dict[str, Any]] = field(default_factory=list)
    comparison_status: str = "legacy"


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


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
        if not _finite_number(level):
            continue
        if level <= 0:
            continue
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            continue
        try:
            when = _parse_as_of(as_of)
            raw_when = datetime.fromisoformat(as_of.strip().replace("Z", "+00:00"))
            timezone_assumed = len(as_of.strip()) != 10 and raw_when.tzinfo is None
        except ValueError:
            continue
        points.append(
            BenchmarkPoint(
                as_of=when,
                level=float(level),
                currency=currency.strip().upper(),
                return_convention=(
                    row["return_convention"].strip()
                    if isinstance(row.get("return_convention"), str)
                    else "unspecified"
                ),
                source=row.get("source")
                if isinstance(row.get("source"), str)
                else None,
                as_of_timezone_assumed=timezone_assumed,
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
    if any(not _finite_number(p.level) or p.level <= 0 for p in (start, end)):
        warnings.append("Benchmark levels must be finite positive numbers")
        return None, warnings
    fraction = (end.level / start.level) - 1.0
    if not _finite_number(fraction) or not _finite_number(fraction * 100):
        warnings.append("Benchmark return arithmetic is nonfinite")
        return None, warnings
    return fraction, warnings


BenchmarkLoader = Callable[[str], list[BenchmarkPoint]]


_SAFE_BENCHMARK_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
)


def _is_safe_benchmark_id(benchmark_id: str) -> bool:
    if not benchmark_id or benchmark_id in {".", ".."}:
        return False
    if benchmark_id.startswith("."):
        # Reject hidden files and any leading-dot tricks ('.', '..', '.foo').
        return False
    return all(ch in _SAFE_BENCHMARK_ID_CHARS for ch in benchmark_id)


def make_dir_loader(benchmarks_dir: str | Path) -> BenchmarkLoader:
    """Default loader: ``<benchmarks_dir>/<id>.jsonl``.

    Benchmark ids are policy-provided, so the loader confines lookups to
    ``benchmarks_dir`` — ids containing path separators, ``..``
    components, or other unsafe characters return an empty series rather
    than reading arbitrary files outside the directory.
    """

    base = Path(benchmarks_dir).resolve()

    def _load(benchmark_id: str) -> list[BenchmarkPoint]:
        if not _is_safe_benchmark_id(benchmark_id):
            return []
        candidate = (base / f"{benchmark_id}.jsonl").resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            return []
        if not candidate.exists():
            return []
        return load_benchmark_series(candidate)

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
    historical_fx: HistoricalFx | None = None,
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
            comparison_status="unavailable" if historical_fx is not None else "legacy",
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
            comparison_status="unavailable" if historical_fx is not None else "legacy",
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
            historical_fx=historical_fx,
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
            comparison_status="unavailable" if historical_fx is not None else "legacy",
        )

    if historical_fx is not None:
        result = BenchmarkComparison(
            benchmark_id,
            label,
            kind,
            base_currency,
            None,
            None,
            period_start_iso,
            period_end_iso,
            comparison_status="unavailable",
        )
        return _resolve_historical_series(
            result,
            series,
            currency,
            period_start,
            period_end,
            historical_fx,
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


def _resolve_historical_series(
    result: BenchmarkComparison,
    series: list[BenchmarkPoint],
    declared_currency: str,
    period_start: datetime,
    period_end: datetime,
    historical_fx: HistoricalFx,
) -> BenchmarkComparison:
    """Translate actual bookends and certify whether excess is meaningful."""
    if any(
        p.as_of_timezone_assumed
        or p.as_of.tzinfo is None
        or p.as_of.utcoffset() is None
        for p in series
    ):
        result.warnings.append("Benchmark contains ambiguous timezone-naive dates")
        return result
    dates = [p.as_of for p in series]
    if len(set(dates)) != len(dates):
        result.warnings.append("Benchmark contains ambiguous duplicate dates")
        return result
    series = sorted(series, key=lambda p: p.as_of)
    start, end = _select_bookends(series, period_start, period_end)
    fraction, warnings = benchmark_native_twr(series, period_start, period_end)
    result.warnings.extend(warnings)
    if start is None or end is None:
        return result
    result.period_start = start.as_of.isoformat()
    result.period_end = end.as_of.isoformat()
    result.native_currency = start.currency
    result.data_provenance = [
        {
            "bookend": role,
            "as_of": p.as_of.isoformat(),
            "level": p.level if _finite_number(p.level) else None,
            "currency": p.currency,
            "source": p.source,
            "return_convention": p.return_convention,
        }
        for role, p in (("start", start), ("end", end))
    ]
    result.return_convention = (
        start.return_convention
        if start.return_convention == end.return_convention
        else "unspecified"
    )
    if any(
        not isinstance(p.currency, str) or re.fullmatch(r"[A-Z]{3}", p.currency) is None
        for p in (start, end)
    ):
        result.warnings.append(
            "Benchmark bookend currency must be a three-letter uppercase code; historical FX unavailable"
        )
        return result
    if fraction is None:
        return result
    result.native_twr_pct = round(fraction * 100, 6)
    if declared_currency and start.currency != declared_currency:
        result.warnings.append(
            "Benchmark series currency does not match declared currency"
        )
        return result
    translated: list[float] = []
    for role, p in (("start", start), ("end", end)):
        resolved = historical_fx.resolve(p.currency, p.as_of)
        valid_rate = _finite_number(resolved.rate) and resolved.rate > 0
        result.fx_evidence.append(
            {
                "bookend": role,
                "currency": p.currency,
                "requested_at": p.as_of.isoformat(),
                "rate": resolved.rate if valid_rate else None,
                "status": resolved.status,
                "reason": resolved.reason,
                "evidence": dict(resolved.evidence),
            }
        )
        if resolved.status != "available" or not valid_rate:
            result.warnings.append(
                f"Benchmark {role} historical FX unavailable: {resolved.reason or 'invalid_rate'}"
            )
            continue
        converted = p.level * resolved.rate
        if not _finite_number(converted) or converted <= 0:
            result.warnings.append(
                f"Benchmark {role} converted level is not finite and positive"
            )
            continue
        translated.append(converted)
    if len(translated) != 2:
        return result
    converted_pct = (translated[1] / translated[0] - 1) * 100
    if not _finite_number(converted_pct):
        result.warnings.append("Benchmark translated return arithmetic is nonfinite")
        return result
    result.twr_pct = round(converted_pct, 6)
    result.comparison_status = "comparable"
    if start.as_of != period_start or end.as_of != period_end:
        result.warnings.append(
            "Benchmark bookend window does not match portfolio window; excess unavailable"
        )
        result.comparison_status = "not_comparable"
    if result.return_convention != "total_return":
        result.warnings.append(
            "Benchmark return convention must be consistent total_return for excess; price-only/unknown excess unavailable"
        )
        result.comparison_status = "not_comparable"
    if any(not isinstance(p.source, str) or not p.source.strip() for p in (start, end)):
        result.warnings.append(
            "Benchmark bookends require nonblank source provenance for excess"
        )
        result.comparison_status = "not_comparable"
    if result.comparison_status == "comparable":
        result.warnings.append(
            "Comparison assumes portfolio snapshot valuations represent total-return performance"
        )
    return result


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
    historical_fx: HistoricalFx | None = None,
) -> BenchmarkComparison:
    components_raw = bench.get("components") or []
    component_results: list[BenchmarkComparison] = []
    weights: list[tuple[BenchmarkComparison, float]] = []
    warnings: list[str] = []
    total_weight = 0.0
    invalid_components = False
    if historical_fx is not None and not isinstance(components_raw, list):
        components_raw = []
        invalid_components = True

    for comp in components_raw:
        if not isinstance(comp, dict):
            invalid_components = True
            continue
        ref = comp.get("benchmark_id")
        weight = comp.get("weight_pct")
        if not isinstance(ref, str) or not ref:
            invalid_components = True
            continue
        if not _finite_number(weight):
            invalid_components = True
            continue
        if historical_fx is not None and weight < 0:
            invalid_components = True
            continue
        if historical_fx is not None and weight == 0:
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
            historical_fx=historical_fx,
        )
        component_results.append(sub)
        weights.append((sub, float(weight)))
        total_weight += float(weight)

    if historical_fx is not None:
        result = BenchmarkComparison(
            str(bench.get("id") or ""),
            label,
            "composite",
            base_currency,
            None,
            None,
            period_start_iso,
            period_end_iso,
            components=component_results,
            comparison_status="unavailable",
        )
        for sub, _ in weights:
            result.fx_evidence.extend(
                {**item, "component_id": sub.benchmark_id} for item in sub.fx_evidence
            )
            result.data_provenance.extend(
                {**item, "component_id": sub.benchmark_id}
                for item in sub.data_provenance
            )
        if (
            invalid_components
            or not _finite_number(total_weight)
            or abs(total_weight - 100) > 1e-6
        ):
            result.warnings.append(
                "Composite requires finite nonnegative weights totaling 100% (tolerance 1e-6)"
            )
            return result
        if any(sub.twr_pct is None for sub, _ in weights):
            result.warnings.append(
                "Composite positive-weight component unavailable; no partial blend or renormalization"
            )
            return result
        try:
            blended = math.fsum(sub.twr_pct * (w / 100) for sub, w in weights)
        except OverflowError:
            blended = math.inf
        if not _finite_number(blended):
            result.warnings.append("Composite return arithmetic is nonfinite")
            return result
        result.twr_pct = round(blended, 6)
        comparable = all(sub.comparison_status == "comparable" for sub, _ in weights)
        result.return_convention = (
            "total_return"
            if all(sub.return_convention == "total_return" for sub, _ in weights)
            else "unspecified"
        )
        result.comparison_status = "comparable" if comparable else "not_comparable"
        if not comparable:
            result.warnings.append(
                "Composite excess unavailable: every positive-weight component must be comparable"
            )
        else:
            result.warnings.append(
                "Comparison assumes portfolio snapshot valuations represent total-return performance"
            )
        return result

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
            blended = round(blended, 6) if _finite_number(blended) else None
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
    *,
    historical_fx: HistoricalFx | None = None,
) -> list[BenchmarkComparison]:
    """Resolve every distinct benchmark referenced by strategic_allocation.

    Without historical FX, excess requires a matching native currency.
    Historical FX compares translated bookends only for the exact portfolio
    window with sourced total-return levels in every active component.
    """

    if historical_fx is not None:
        if (
            period_start.tzinfo is None
            or period_start.utcoffset() is None
            or period_end.tzinfo is None
            or period_end.utcoffset() is None
        ):
            raise ValueError(
                "Historical benchmark window must use timezone-aware datetimes"
            )
        if period_start >= period_end:
            raise ValueError("Historical benchmark window must increase")
        if historical_fx.base_currency != base_currency.strip().upper():
            raise ValueError(
                "Historical FX reporting currency must match portfolio base currency"
            )
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
            historical_fx=historical_fx,
        )
        if (
            comp.twr_pct is not None
            and _finite_number(portfolio_twr_pct)
            and (historical_fx is None or comp.comparison_status == "comparable")
            and comp.currency
            and comp.currency.upper() == base
        ):
            excess = portfolio_twr_pct - comp.twr_pct
            comp.excess_pct = round(excess, 6) if _finite_number(excess) else None
        elif (
            comp.twr_pct is not None and comp.currency and comp.currency.upper() != base
        ):
            comp.warnings.append(
                f"Benchmark currency {comp.currency} != base {base}; excess "
                "return not computed (FX translation deferred)"
            )
        results.append(comp)
    return results
