"""Portfolio performance: time-weighted (Modified Dietz) and money-weighted (XIRR) returns.

MVP scope (Phase 2 / Step 5):
- Portfolio-level only. Per-account / per-bucket attribution and benchmark
  comparison are deferred to follow-up slices.
- Pure functions on already-base-converted cashflows; the orchestrator
  ``compute_performance`` handles snapshot/activity wiring and FX with the
  same fallback rules used by ``aggregate_portfolio``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

# External cashflows = money/assets crossing the portfolio boundary.
# Internal events (buy/sell/dividend/interest/fee/income/reimbursement/
# tax_withheld/fx_conversion/split/merger) reshuffle value within the
# portfolio and must NOT be counted as external cashflow.
_EXTERNAL_FLOW_SIGNS: dict[str, float] = {
    "contribution": 1.0,
    "transfer_in": 1.0,
    "withdrawal": -1.0,
    "transfer_out": -1.0,
}


@dataclass(frozen=True)
class Cashflow:
    when: datetime
    amount_base: float


@dataclass
class PerformanceResult:
    base_currency: str
    period_start: str
    period_end: str
    start_value_base: float
    end_value_base: float
    net_external_cashflow_base: float
    twr_pct: float | None
    mwr_pct: float | None
    cashflow_count: int
    warnings: list[str] = field(default_factory=list)


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _years_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / (365.0 * 24 * 3600)


def modified_dietz(
    start_value: float,
    end_value: float,
    cashflows: Iterable[Cashflow],
    period_start: datetime,
    period_end: datetime,
) -> float | None:
    """Modified Dietz time-weighted return as a fraction (e.g. 0.05 == +5%).

    Returns ``None`` when the denominator is non-positive (no invested capital
    over the period) — a return is undefined in that case.
    """

    total_seconds = (period_end - period_start).total_seconds()
    if total_seconds <= 0:
        return None
    flows = list(cashflows)
    weighted = 0.0
    net_flow = 0.0
    for cf in flows:
        if cf.when < period_start or cf.when > period_end:
            continue
        weight = (period_end - cf.when).total_seconds() / total_seconds
        weighted += weight * cf.amount_base
        net_flow += cf.amount_base
    denom = start_value + weighted
    if denom <= 0:
        return None
    return (end_value - start_value - net_flow) / denom


def xirr(
    cashflows: list[Cashflow],
    *,
    guess: float = 0.1,
    max_iter: int = 100,
    tol: float = 1e-9,
) -> float | None:
    """Money-weighted (internal) rate of return as an annualized fraction.

    Cashflows follow the investor's perspective: negative for money paid in,
    positive for money received. Caller is responsible for assembling the
    series including the initial book value (negative) and terminal value
    (positive).

    Returns ``None`` if a root cannot be bracketed or convergence fails.
    """

    if len(cashflows) < 2:
        return None
    has_pos = any(cf.amount_base > 0 for cf in cashflows)
    has_neg = any(cf.amount_base < 0 for cf in cashflows)
    if not (has_pos and has_neg):
        return None
    t0 = min(cf.when for cf in cashflows)
    times = [_years_between(t0, cf.when) for cf in cashflows]
    amounts = [cf.amount_base for cf in cashflows]

    def npv(rate: float) -> float:
        total = 0.0
        for amt, t in zip(amounts, times):
            total += amt / (1.0 + rate) ** t
        return total

    def dnpv(rate: float) -> float:
        total = 0.0
        for amt, t in zip(amounts, times):
            if t == 0.0:
                continue
            total += -t * amt / (1.0 + rate) ** (t + 1.0)
        return total

    rate = guess
    for _ in range(max_iter):
        if rate <= -1.0:
            rate = -0.999999
        try:
            value = npv(rate)
        except OverflowError:
            break
        if abs(value) < tol:
            return rate
        deriv = dnpv(rate)
        if deriv == 0.0:
            break
        step = value / deriv
        new_rate = rate - step
        if new_rate <= -1.0:
            new_rate = (rate - 1.0) / 2.0
        if abs(new_rate - rate) < tol:
            return new_rate
        rate = new_rate

    # Bisection fallback over a generous range.
    lo, hi = -0.999999, 10.0
    try:
        f_lo, f_hi = npv(lo), npv(hi)
    except OverflowError:
        return None
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def _resolve_to_base(
    amount: float,
    currency: str,
    base_currency: str,
    *,
    metadata: Any,
    fx_rates_to_base: dict[str, float],
) -> float | None:
    code = currency.strip().upper()
    if code == base_currency:
        return amount
    rate = fx_rates_to_base.get(code)
    if rate is not None and rate > 0:
        return amount * rate
    if isinstance(metadata, dict):
        meta_fx = metadata.get("fx_rate_to_base")
        if isinstance(meta_fx, (int, float)) and not isinstance(meta_fx, bool) and meta_fx > 0:
            return amount * float(meta_fx)
    return None


def _is_posted(activity: dict[str, Any]) -> bool:
    status = activity.get("status")
    if status is None:
        return True
    if not isinstance(status, str):
        return False
    s = status.strip().lower()
    return not s or s == "posted"


def extract_external_cashflows(
    activities: list[dict[str, Any]],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float] | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> tuple[list[Cashflow], list[str]]:
    """Pull external cashflows from the activity ledger, base-converted.

    Skipped activities (foreign currency without a usable FX rate, malformed
    money, unparsable dates) are surfaced as warnings instead of errors so
    a partial answer is still produced.
    """

    rates = {k.strip().upper(): float(v) for k, v in (fx_rates_to_base or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
    flows: list[Cashflow] = []
    warnings: list[str] = []
    for act in activities:
        if not isinstance(act, dict):
            continue
        if not _is_posted(act):
            continue
        event_type = str(act.get("event_type", "")).strip().lower()
        sign = _EXTERNAL_FLOW_SIGNS.get(event_type)
        if sign is None:
            continue
        money = act.get("money")
        if not isinstance(money, dict):
            continue
        amount = money.get("amount")
        currency = money.get("currency")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        if not isinstance(currency, str) or not currency.strip():
            continue
        when_raw = act.get("effective_at")
        if not isinstance(when_raw, str):
            continue
        try:
            when = _parse_iso(when_raw)
        except ValueError:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has unparsable effective_at; skipped"
            )
            continue
        if period_start is not None and when < period_start:
            continue
        if period_end is not None and when > period_end:
            continue
        base_amount = _resolve_to_base(
            float(amount),
            currency,
            base_currency,
            metadata=act.get("metadata"),
            fx_rates_to_base=rates,
        )
        if base_amount is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' missing FX rate "
                f"for {currency!r} -> {base_currency!r}; cashflow skipped"
            )
            continue
        flows.append(Cashflow(when=when, amount_base=sign * base_amount))
    flows.sort(key=lambda cf: cf.when)
    return flows, warnings


def _select_bookend_snapshots(
    snapshots: list[dict[str, Any]],
    since: datetime | None,
    until: datetime | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick start/end snapshots for the requested window.

    Start: the latest snapshot at-or-before ``since`` if one exists, else the
    earliest snapshot in the window. End: the latest snapshot at-or-before
    ``until`` (defaults to the most recent snapshot overall).
    """

    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for snap in snapshots:
        ts = snap.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            parsed.append((_parse_iso(ts), snap))
        except ValueError:
            continue
    parsed.sort(key=lambda row: row[0])
    if not parsed:
        return None, None

    end_snap: dict[str, Any] | None = None
    if until is None:
        end_snap = parsed[-1][1]
    else:
        for ts, snap in reversed(parsed):
            if ts <= until:
                end_snap = snap
                break

    start_snap: dict[str, Any] | None = None
    if since is None:
        start_snap = parsed[0][1]
    else:
        for ts, snap in reversed(parsed):
            if ts <= since:
                start_snap = snap
                break
        if start_snap is None:
            for ts, snap in parsed:
                if ts >= since:
                    start_snap = snap
                    break
    return start_snap, end_snap


def _snap_value(snap: dict[str, Any]) -> float | None:
    totals = snap.get("totals")
    if not isinstance(totals, dict):
        return None
    value = totals.get("portfolio_value_base")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def compute_performance(
    snapshots: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float] | None = None,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> PerformanceResult:
    since_dt = _parse_iso(since) if isinstance(since, str) else since
    until_dt = _parse_iso(until) if isinstance(until, str) else until

    start_snap, end_snap = _select_bookend_snapshots(snapshots, since_dt, until_dt)
    warnings: list[str] = []

    if start_snap is None or end_snap is None:
        warnings.append("No snapshots available for the requested window")
        return PerformanceResult(
            base_currency=base_currency,
            period_start="",
            period_end="",
            start_value_base=0.0,
            end_value_base=0.0,
            net_external_cashflow_base=0.0,
            twr_pct=None,
            mwr_pct=None,
            cashflow_count=0,
            warnings=warnings,
        )

    start_ts = _parse_iso(start_snap["timestamp"])
    end_ts = _parse_iso(end_snap["timestamp"])
    start_value = _snap_value(start_snap)
    end_value = _snap_value(end_snap)
    if start_value is None or end_value is None:
        warnings.append("Snapshot is missing portfolio_value_base; cannot compute return")
        return PerformanceResult(
            base_currency=base_currency,
            period_start=start_snap.get("timestamp", ""),
            period_end=end_snap.get("timestamp", ""),
            start_value_base=start_value or 0.0,
            end_value_base=end_value or 0.0,
            net_external_cashflow_base=0.0,
            twr_pct=None,
            mwr_pct=None,
            cashflow_count=0,
            warnings=warnings,
        )

    cashflows, cf_warnings = extract_external_cashflows(
        activities,
        base_currency,
        fx_rates_to_base=fx_rates_to_base,
        period_start=start_ts,
        period_end=end_ts,
    )
    warnings.extend(cf_warnings)

    twr_fraction = modified_dietz(
        start_value, end_value, cashflows, start_ts, end_ts
    )

    xirr_series = [Cashflow(when=start_ts, amount_base=-start_value)]
    for cf in cashflows:
        xirr_series.append(Cashflow(when=cf.when, amount_base=-cf.amount_base))
    xirr_series.append(Cashflow(when=end_ts, amount_base=end_value))
    mwr_fraction = xirr(xirr_series)

    net_flow = sum(cf.amount_base for cf in cashflows)

    return PerformanceResult(
        base_currency=base_currency,
        period_start=start_snap.get("timestamp", ""),
        period_end=end_snap.get("timestamp", ""),
        start_value_base=round(start_value, 2),
        end_value_base=round(end_value, 2),
        net_external_cashflow_base=round(net_flow, 2),
        twr_pct=None if twr_fraction is None else round(twr_fraction * 100, 6),
        mwr_pct=None if mwr_fraction is None else round(mwr_fraction * 100, 6),
        cashflow_count=len(cashflows),
        warnings=warnings,
    )
