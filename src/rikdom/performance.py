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
from datetime import datetime, time, timezone
from typing import Any, Iterable

from .benchmarks import (
    BenchmarkComparison,
    BenchmarkLoader,
    resolve_benchmarks_for_targets,
)

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
    benchmarks: list[BenchmarkComparison] = field(default_factory=list)


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_date_only(value: str) -> bool:
    text = value.strip()
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _parse_until_bound(value: str) -> datetime:
    dt = _parse_iso(value)
    if _is_date_only(value):
        return datetime.combine(dt.date(), time.max, tzinfo=timezone.utc)
    return dt


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
        if (
            isinstance(meta_fx, (int, float))
            and not isinstance(meta_fx, bool)
            and meta_fx > 0
        ):
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


def _normalize_fx_rates(fx_rates_to_base: dict[str, float] | None) -> dict[str, float]:
    return {
        k.strip().upper(): float(v)
        for k, v in (fx_rates_to_base or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    }


def _coerce_bound(
    value: str | datetime | None, *, until: bool = False
) -> datetime | None:
    if isinstance(value, str):
        return _parse_until_bound(value) if until else _parse_iso(value)
    return value


def performance_period_bounds(
    snapshots: list[dict[str, Any]],
    *,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Return the effective snapshot-bounded performance window."""

    since_dt = _coerce_bound(since)
    until_dt = _coerce_bound(until, until=True)
    start_snap, end_snap = _select_bookend_snapshots(snapshots, since_dt, until_dt)
    if start_snap is None or end_snap is None:
        return None, None
    try:
        return _parse_iso(start_snap["timestamp"]), _parse_iso(end_snap["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None, None


def external_cashflow_currencies(
    activities: list[dict[str, Any]],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float] | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> list[str]:
    base = base_currency.strip().upper()
    rates = _normalize_fx_rates(fx_rates_to_base)
    currencies: set[str] = set()
    for act in activities:
        if not isinstance(act, dict) or not _is_posted(act):
            continue
        event_type = str(act.get("event_type", "")).strip().lower()
        if event_type not in _EXTERNAL_FLOW_SIGNS:
            continue
        money = act.get("money")
        if not isinstance(money, dict):
            continue
        amount = money.get("amount")
        currency = money.get("currency")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        if not isinstance(currency, str):
            continue
        code = currency.strip().upper()
        if len(code) != 3 or code == base:
            continue
        if period_start is not None or period_end is not None:
            when_raw = act.get("effective_at")
            if not isinstance(when_raw, str):
                continue
            try:
                when = _parse_iso(when_raw)
            except ValueError:
                continue
            if period_start is not None and when < period_start:
                continue
            if period_end is not None and when > period_end:
                continue
        if (
            _resolve_to_base(
                abs(float(amount)),
                code,
                base,
                metadata=act.get("metadata"),
                fx_rates_to_base=rates,
            )
            is None
        ):
            currencies.add(code)
    return sorted(currencies)


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

    rates = _normalize_fx_rates(fx_rates_to_base)
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
            abs(float(amount)),
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


def _snap_by_account(snap: dict[str, Any]) -> dict[str, float]:
    totals = snap.get("totals")
    if not isinstance(totals, dict):
        return {}
    by_account = totals.get("by_account")
    if not isinstance(by_account, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in by_account.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = float(v)
    return out


UNASSIGNED_ACCOUNT = "__unassigned__"


@dataclass
class AccountPerformance:
    account_id: str
    start_value_base: float
    end_value_base: float
    net_external_cashflow_base: float
    twr_pct: float | None
    mwr_pct: float | None
    cashflow_count: int
    warnings: list[str] = field(default_factory=list)


def _snap_by_strategic_bucket(snap: dict[str, Any]) -> dict[str, float]:
    totals = snap.get("totals")
    if not isinstance(totals, dict):
        return {}
    by_bucket = totals.get("by_strategic_bucket")
    if not isinstance(by_bucket, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in by_bucket.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = float(v)
    return out


def _build_holding_bucket_index(
    portfolio: dict[str, Any] | None,
    policy: dict[str, Any] | None,
) -> dict[str, str]:
    """Map ``holding_id`` → strategic bucket key (asset_class targets only).

    Other dimensions (region/currency/...) are out of scope for cashflow
    attribution — a single buy/sell rarely lands on a single look-through
    bucket. Holdings whose asset_class isn't covered by any asset_class
    target are mapped to ``__unallocated__``.
    """

    if not isinstance(portfolio, dict) or not isinstance(policy, dict):
        return {}
    catalog = portfolio.get("asset_type_catalog") or []
    class_index: dict[str, str] = {}
    for item in catalog:
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        cls = item.get("asset_class")
        if isinstance(tid, str) and isinstance(cls, str):
            class_index[tid] = cls

    target_classes: set[str] = set()
    strat = policy.get("strategic_allocation")
    if isinstance(strat, dict):
        for tgt in strat.get("targets") or []:
            if not isinstance(tgt, dict):
                continue
            if tgt.get("dimension") != "asset_class":
                continue
            bucket = tgt.get("bucket")
            if isinstance(bucket, str) and bucket:
                target_classes.add(bucket)

    holdings = portfolio.get("holdings") or []
    out: dict[str, str] = {}
    for h in holdings:
        if not isinstance(h, dict):
            continue
        hid = h.get("id")
        type_id = h.get("asset_type_id")
        if not isinstance(hid, str) or not isinstance(type_id, str):
            continue
        cls = class_index.get(type_id)
        if cls and cls in target_classes:
            out[hid] = f"asset_class:{cls}"
        else:
            out[hid] = "__unallocated__"
    return out


def _attribute_external_cashflows_by_strategic_bucket(
    activities: list[dict[str, Any]],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float] | None,
    period_start: datetime,
    period_end: datetime,
    holding_to_bucket: dict[str, str],
) -> tuple[dict[str, list[Cashflow]], list[str]]:
    rates = _normalize_fx_rates(fx_rates_to_base)
    buckets: dict[str, list[Cashflow]] = {}
    warnings: list[str] = []
    for act in activities:
        if not isinstance(act, dict) or not _is_posted(act):
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
            continue
        if when < period_start or when > period_end:
            continue
        base_amount = _resolve_to_base(
            abs(float(amount)),
            currency,
            base_currency,
            metadata=act.get("metadata"),
            fx_rates_to_base=rates,
        )
        if base_amount is None:
            continue

        hid = act.get("holding_id")
        bucket_key: str
        if isinstance(hid, str) and hid in holding_to_bucket:
            bucket_key = holding_to_bucket[hid]
        else:
            bucket_key = "__unallocated__"
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has no holding_id "
                "(or holding not found); attributed to '__unallocated__' "
                "for per-bucket performance"
            )
        buckets.setdefault(bucket_key, []).append(
            Cashflow(when=when, amount_base=sign * base_amount)
        )
    for flows in buckets.values():
        flows.sort(key=lambda cf: cf.when)
    return buckets, warnings


@dataclass
class StrategicBucketPerformance:
    bucket_key: str
    start_value_base: float
    end_value_base: float
    net_external_cashflow_base: float
    twr_pct: float | None
    mwr_pct: float | None
    cashflow_count: int
    warnings: list[str] = field(default_factory=list)


def compute_performance_by_strategic_bucket(
    snapshots: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    *,
    base_currency: str,
    portfolio: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    fx_rates_to_base: dict[str, float] | None = None,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> tuple[list[StrategicBucketPerformance], list[str]]:
    """Per-bucket TWR/MWR using ``totals.by_strategic_bucket`` bookends.

    Cashflow attribution is restricted to asset_class targets (a single
    buy/sell can't be cleanly split across look-through dimensions).
    Activities without a ``holding_id`` — or whose holding is not covered
    by any asset_class target — fall under ``__unallocated__``.
    """

    since_dt = _parse_iso(since) if isinstance(since, str) else since
    until_dt = _parse_until_bound(until) if isinstance(until, str) else until

    start_snap, end_snap = _select_bookend_snapshots(snapshots, since_dt, until_dt)
    if start_snap is None or end_snap is None:
        return [], ["No snapshots available for the requested window"]

    start_ts = _parse_iso(start_snap["timestamp"])
    end_ts = _parse_iso(end_snap["timestamp"])

    start_buckets = _snap_by_strategic_bucket(start_snap)
    end_buckets = _snap_by_strategic_bucket(end_snap)
    top_warnings: list[str] = []
    if not start_buckets:
        top_warnings.append(
            "Start snapshot is missing totals.by_strategic_bucket; "
            "per-bucket TWR unavailable"
        )
    if not end_buckets:
        top_warnings.append(
            "End snapshot is missing totals.by_strategic_bucket; "
            "per-bucket TWR unavailable"
        )
    if not start_buckets or not end_buckets:
        return [], top_warnings

    holding_to_bucket = _build_holding_bucket_index(portfolio, policy)
    cashflows_by_bucket, attribution_warnings = (
        _attribute_external_cashflows_by_strategic_bucket(
            activities,
            base_currency,
            fx_rates_to_base=fx_rates_to_base,
            period_start=start_ts,
            period_end=end_ts,
            holding_to_bucket=holding_to_bucket,
        )
    )
    top_warnings.extend(attribution_warnings)

    bucket_keys = sorted(
        set(start_buckets) | set(end_buckets) | set(cashflows_by_bucket)
    )

    results: list[StrategicBucketPerformance] = []
    for key in bucket_keys:
        start_value = start_buckets.get(key, 0.0)
        end_value = end_buckets.get(key, 0.0)
        flows = cashflows_by_bucket.get(key, [])
        bucket_warnings: list[str] = []
        if key not in start_buckets:
            bucket_warnings.append(
                "Bucket not present in start snapshot; start_value treated as 0"
            )
        if key not in end_buckets:
            bucket_warnings.append(
                "Bucket not present in end snapshot; end_value treated as 0"
            )
        if (
            key != "__unallocated__"
            and not key.startswith("asset_class:")
            and flows
        ):
            bucket_warnings.append(
                "Cashflow attribution is only computed for asset_class targets"
            )

        twr_fraction = modified_dietz(
            start_value, end_value, flows, start_ts, end_ts
        )

        if start_value > 0 or flows or end_value > 0:
            xirr_series: list[Cashflow] = []
            if start_value > 0:
                xirr_series.append(
                    Cashflow(when=start_ts, amount_base=-start_value)
                )
            for cf in flows:
                xirr_series.append(
                    Cashflow(when=cf.when, amount_base=-cf.amount_base)
                )
            if end_value != 0:
                xirr_series.append(Cashflow(when=end_ts, amount_base=end_value))
            mwr_fraction = xirr(xirr_series)
        else:
            mwr_fraction = None

        net_flow = sum(cf.amount_base for cf in flows)
        results.append(
            StrategicBucketPerformance(
                bucket_key=key,
                start_value_base=round(start_value, 2),
                end_value_base=round(end_value, 2),
                net_external_cashflow_base=round(net_flow, 2),
                twr_pct=None if twr_fraction is None else round(twr_fraction * 100, 6),
                mwr_pct=None if mwr_fraction is None else round(mwr_fraction * 100, 6),
                cashflow_count=len(flows),
                warnings=bucket_warnings,
            )
        )
    return results, top_warnings


def _attribute_external_cashflows_by_account(
    activities: list[dict[str, Any]],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float] | None,
    period_start: datetime,
    period_end: datetime,
) -> tuple[dict[str, list[Cashflow]], list[str]]:
    """Bucket external cashflows by ``activity.account_id``.

    Activities without an ``account_id`` land under ``UNASSIGNED_ACCOUNT``
    so the attribution is conservative — callers can warn on that bucket
    if the policy implies every flow should belong to an account.
    """

    rates = _normalize_fx_rates(fx_rates_to_base)
    buckets: dict[str, list[Cashflow]] = {}
    warnings: list[str] = []
    for act in activities:
        if not isinstance(act, dict) or not _is_posted(act):
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
            continue
        if when < period_start or when > period_end:
            continue
        base_amount = _resolve_to_base(
            abs(float(amount)),
            currency,
            base_currency,
            metadata=act.get("metadata"),
            fx_rates_to_base=rates,
        )
        if base_amount is None:
            continue

        raw_account = act.get("account_id")
        account_key = (
            raw_account.strip()
            if isinstance(raw_account, str) and raw_account.strip()
            else UNASSIGNED_ACCOUNT
        )
        if account_key == UNASSIGNED_ACCOUNT:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has no account_id; "
                "attributed to '__unassigned__' for per-account performance"
            )
        buckets.setdefault(account_key, []).append(
            Cashflow(when=when, amount_base=sign * base_amount)
        )
    for flows in buckets.values():
        flows.sort(key=lambda cf: cf.when)
    return buckets, warnings


def compute_performance_by_account(
    snapshots: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float] | None = None,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> tuple[list[AccountPerformance], list[str]]:
    """Per-account TWR/MWR using ``totals.by_account`` bookend values.

    Returns a list of ``AccountPerformance`` (one per account observed in
    either bookend snapshot or in attributed activities) plus a list of
    top-level warnings (e.g. snapshots missing ``by_account``).
    """

    since_dt = _parse_iso(since) if isinstance(since, str) else since
    until_dt = _parse_until_bound(until) if isinstance(until, str) else until

    start_snap, end_snap = _select_bookend_snapshots(snapshots, since_dt, until_dt)
    if start_snap is None or end_snap is None:
        return [], ["No snapshots available for the requested window"]

    start_ts = _parse_iso(start_snap["timestamp"])
    end_ts = _parse_iso(end_snap["timestamp"])

    start_by_account = _snap_by_account(start_snap)
    end_by_account = _snap_by_account(end_snap)
    top_warnings: list[str] = []
    if not start_by_account:
        top_warnings.append(
            "Start snapshot is missing totals.by_account; per-account TWR unavailable"
        )
    if not end_by_account:
        top_warnings.append(
            "End snapshot is missing totals.by_account; per-account TWR unavailable"
        )
    if not start_by_account or not end_by_account:
        return [], top_warnings

    cashflows_by_account, attribution_warnings = (
        _attribute_external_cashflows_by_account(
            activities,
            base_currency,
            fx_rates_to_base=fx_rates_to_base,
            period_start=start_ts,
            period_end=end_ts,
        )
    )
    top_warnings.extend(attribution_warnings)

    account_ids = sorted(
        set(start_by_account)
        | set(end_by_account)
        | set(cashflows_by_account)
    )

    results: list[AccountPerformance] = []
    for aid in account_ids:
        start_value = start_by_account.get(aid, 0.0)
        end_value = end_by_account.get(aid, 0.0)
        flows = cashflows_by_account.get(aid, [])
        warnings: list[str] = []
        if aid not in start_by_account:
            warnings.append(
                "Account not present in start snapshot; start_value treated as 0"
            )
        if aid not in end_by_account:
            warnings.append(
                "Account not present in end snapshot; end_value treated as 0"
            )

        twr_fraction = modified_dietz(
            start_value, end_value, flows, start_ts, end_ts
        )

        if start_value > 0 or flows or end_value > 0:
            xirr_series: list[Cashflow] = []
            if start_value > 0:
                xirr_series.append(
                    Cashflow(when=start_ts, amount_base=-start_value)
                )
            for cf in flows:
                xirr_series.append(
                    Cashflow(when=cf.when, amount_base=-cf.amount_base)
                )
            if end_value != 0:
                xirr_series.append(Cashflow(when=end_ts, amount_base=end_value))
            mwr_fraction = xirr(xirr_series)
        else:
            mwr_fraction = None

        net_flow = sum(cf.amount_base for cf in flows)
        results.append(
            AccountPerformance(
                account_id=aid,
                start_value_base=round(start_value, 2),
                end_value_base=round(end_value, 2),
                net_external_cashflow_base=round(net_flow, 2),
                twr_pct=None if twr_fraction is None else round(twr_fraction * 100, 6),
                mwr_pct=None if mwr_fraction is None else round(mwr_fraction * 100, 6),
                cashflow_count=len(flows),
                warnings=warnings,
            )
        )
    return results, top_warnings


def compute_performance(
    snapshots: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    *,
    base_currency: str,
    fx_rates_to_base: dict[str, float] | None = None,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    policy: dict[str, Any] | None = None,
    benchmark_loader: BenchmarkLoader | None = None,
) -> PerformanceResult:
    since_dt = _parse_iso(since) if isinstance(since, str) else since
    until_dt = _parse_until_bound(until) if isinstance(until, str) else until

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
        warnings.append(
            "Snapshot is missing portfolio_value_base; cannot compute return"
        )
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

    twr_fraction = modified_dietz(start_value, end_value, cashflows, start_ts, end_ts)

    xirr_series = [Cashflow(when=start_ts, amount_base=-start_value)]
    for cf in cashflows:
        xirr_series.append(Cashflow(when=cf.when, amount_base=-cf.amount_base))
    xirr_series.append(Cashflow(when=end_ts, amount_base=end_value))
    mwr_fraction = xirr(xirr_series)

    net_flow = sum(cf.amount_base for cf in cashflows)

    twr_pct = None if twr_fraction is None else round(twr_fraction * 100, 6)
    benchmark_comparisons: list[BenchmarkComparison] = []
    if policy is not None and benchmark_loader is not None:
        benchmark_comparisons = resolve_benchmarks_for_targets(
            policy,
            benchmark_loader,
            start_ts,
            end_ts,
            base_currency,
            start_snap.get("timestamp", ""),
            end_snap.get("timestamp", ""),
            twr_pct,
        )

    return PerformanceResult(
        base_currency=base_currency,
        period_start=start_snap.get("timestamp", ""),
        period_end=end_snap.get("timestamp", ""),
        start_value_base=round(start_value, 2),
        end_value_base=round(end_value, 2),
        net_external_cashflow_base=round(net_flow, 2),
        twr_pct=twr_pct,
        mwr_pct=None if mwr_fraction is None else round(mwr_fraction * 100, 6),
        cashflow_count=len(cashflows),
        warnings=warnings,
        benchmarks=benchmark_comparisons,
    )
