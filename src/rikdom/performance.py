"""Portfolio linked TWR, disclosed Modified Dietz approximations, and XIRR.

Explicit before/after flow evidence supports portfolio linking only. Account
and strategic bucket attribution retain the existing Dietz approximation.
Legacy undated FX and unresolved transfer identity remain approximate.
"""

from __future__ import annotations

from .activities import effective_activities

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any, Iterable
import math
import json

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


def _finite_number(value: Any) -> float | None:
    """Return a representable finite financial number, rejecting bools/overflow."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _return_percent(fraction: float | None) -> float | None:
    if fraction is None:
        return None
    percentage = _finite_number(fraction * 100)
    return None if percentage is None else round(percentage, 6)


def _event_type(activity: dict[str, Any]) -> str:
    """Use the same accepted ledger spelling for extraction and eligibility."""
    return str(activity.get("event_type", "")).strip().lower()


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
    net_external_cashflow_base: float | None
    twr_pct: float | None
    mwr_pct: float | None
    cashflow_count: int
    warnings: list[str] = field(default_factory=list)
    benchmarks: list[BenchmarkComparison] = field(default_factory=list)
    # twr_pct remains the legacy Modified Dietz result. These fields select
    # the best supported period return without changing that contract.
    twr_method: str = "unavailable"
    twr_return_pct: float | None = None
    linked_twr_pct: float | None = None
    twr_fallback_reason: str | None = None
    twr_return_basis: str = "period"
    mwr_return_basis: str = "annualized_365_day"
    legacy_twr_method: str = "modified_dietz"


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class FlowValuation:
    when: datetime
    pre_flow_value_base: float
    post_flow_value_base: float
    source: str


@dataclass(frozen=True)
class FlowValuations:
    """Validated, explicit portfolio cashflow boundaries; never daily snapshots."""

    rounding_tolerance_base: float
    valuations: tuple[FlowValuation, ...]


def read_flow_valuations(path: str) -> Any:
    """Decode sidecar JSON without silently discarding duplicate evidence keys."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"flow-valuations: duplicate JSON key {key!r}")
            result[key] = value
        return result

    with open(path, encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=unique_object)


def parse_flow_valuations(document: Any, base_currency: str) -> FlowValuations:
    """Validate version 1 read-only evidence, including unique UTC instants.

    Structural errors reject the sidecar. Missing/mismatched financial evidence
    is handled separately as a disclosed fallback by the return selector.
    """

    def fail(message: str) -> None:
        raise ValueError(f"flow-valuations: {message}")

    def number(value: Any, path: str) -> float:
        result = _finite_number(value)
        if result is None:
            fail(f"{path} must be a finite number within the supported float range")
        return result

    fields = {
        "version",
        "scope",
        "base_currency",
        "rounding_tolerance_base",
        "valuations",
    }
    if not isinstance(document, dict) or set(document) != fields:
        fail(
            "expected exactly version, scope, base_currency, rounding_tolerance_base, valuations"
        )
    if type(document["version"]) is not int or document["version"] != 1:
        fail("version must be 1")
    if document["scope"] != "portfolio":
        fail("scope must be portfolio; account and bucket evidence is unsupported")
    if document["base_currency"] != base_currency:
        fail(f"base_currency must match portfolio currency {base_currency}")
    tolerance = number(document["rounding_tolerance_base"], "rounding_tolerance_base")
    if tolerance < 0:
        fail("rounding_tolerance_base must be non-negative")
    if not isinstance(document["valuations"], list):
        fail("valuations must be an array")
    rows = []
    seen: set[datetime] = set()
    row_fields = {
        "timestamp",
        "base_currency",
        "pre_flow_value_base",
        "post_flow_value_base",
        "source",
    }
    for index, row in enumerate(document["valuations"]):
        path = f"valuations[{index}]"
        if not isinstance(row, dict) or set(row) != row_fields:
            fail(f"{path} requires exactly {', '.join(sorted(row_fields))}")
        raw = row["timestamp"]
        try:
            if (
                not isinstance(raw, str)
                or "T" not in raw
                or datetime.fromisoformat(raw.replace("Z", "+00:00")).tzinfo is None
            ):
                fail(f"{path}.timestamp must be an ISO datetime with timezone")
            when = _parse_iso(raw)
        except (TypeError, ValueError):
            fail(f"{path}.timestamp must be an ISO datetime with timezone")
        if when in seen:
            fail(f"{path}.timestamp duplicates another boundary instant")
        seen.add(when)
        if row["base_currency"] != base_currency:
            fail(f"{path}.base_currency must match {base_currency}")
        if not isinstance(row["source"], str) or not row["source"].strip():
            fail(f"{path}.source must identify the valuation source")
        rows.append(
            FlowValuation(
                when,
                number(row["pre_flow_value_base"], f"{path}.pre_flow_value_base"),
                number(row["post_flow_value_base"], f"{path}.post_flow_value_base"),
                row["source"].strip(),
            )
        )
    return FlowValuations(tolerance, tuple(sorted(rows, key=lambda row: row.when)))


def _select_twr(
    start_value: float,
    end_value: float,
    flows: list[Cashflow],
    start: datetime,
    end: datetime,
    evidence: FlowValuations | None,
    data_warnings: list[str],
    dietz: float | None,
) -> tuple[float | None, str, str | None]:
    """Choose a supported return and hide boundary reconciliation/linking rules."""

    def fallback(reason: str) -> tuple[float | None, str, str]:
        return dietz, "modified_dietz" if dietz is not None else "unavailable", reason

    if end <= start or start_value <= 0 or end_value < 0:
        return (
            None,
            "unavailable",
            "Positive opening capital, non-negative terminal value and a positive window are required",
        )
    if any("invalid financial" in warning.lower() for warning in data_warnings):
        return None, "unavailable", "Invalid financial inputs in external cashflows"
    if data_warnings:
        return fallback(
            "External cashflow data is incomplete or approximate: "
            + "; ".join(data_warnings)
        )
    grouped: dict[datetime, float] = {}
    for cf in flows:
        grouped[cf.when] = grouped.get(cf.when, 0.0) + cf.amount_base
    rows = (
        {row.when: row for row in evidence.valuations if start <= row.when <= end}
        if evidence
        else {}
    )
    if not grouped and not rows:
        result = _finite_number(end_value / start_value - 1)
        if result is None:
            return None, "unavailable", "Non-finite bookend return"
        return result, "bookend_ratio", None
    if any(_finite_number(amount) is None for amount in grouped.values()):
        return None, "unavailable", "Non-finite aggregate cashflow"
    if set(rows) != set(grouped):
        return fallback(
            "Missing or unmatched explicit before/after cashflow valuation boundaries"
        )
    tolerance = evidence.rounding_tolerance_base if evidence else 0.0
    capital = start_value
    factor = 1.0
    for when, row in sorted(rows.items()):
        pre, post = row.pre_flow_value_base, row.post_flow_value_base
        if pre < 0 or post < 0:
            return None, "unavailable", "Negative capital in flow valuation evidence"
        if abs((post - pre) - grouped[when]) > tolerance:
            return fallback(
                f"Valuation difference does not match aggregate signed cashflow at {when.isoformat()}"
            )
        if when == start and abs(pre - start_value) > tolerance:
            return fallback(
                "Start snapshot must equal pre-flow value at a start-boundary cashflow"
            )
        if when == end and abs(post - end_value) > tolerance:
            return fallback(
                "End snapshot must equal post-flow value at an end-boundary cashflow"
            )
        if capital <= 0:
            return None, "unavailable", "Zero capital prevents a subperiod return"
        factor *= pre / capital
        capital = post
    if end not in rows:
        if capital <= 0:
            return None, "unavailable", "Zero capital prevents a subperiod return"
        factor *= end_value / capital
    result = factor - 1
    if not math.isfinite(result):
        return None, "unavailable", "Non-finite linked return"
    return result, "linked_subperiod", None


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

    if _finite_number(start_value) is None or _finite_number(end_value) is None:
        return None
    total_seconds = (period_end - period_start).total_seconds()
    if total_seconds <= 0:
        return None
    flows = list(cashflows)
    weighted = 0.0
    net_flow = 0.0
    for cf in flows:
        if cf.when < period_start or cf.when > period_end:
            continue
        if _finite_number(cf.amount_base) is None:
            return None
        weight = (period_end - cf.when).total_seconds() / total_seconds
        weighted += weight * cf.amount_base
        net_flow += cf.amount_base
    denom = start_value + weighted
    if denom <= 0 or not math.isfinite(denom):
        return None
    result = (end_value - start_value - net_flow) / denom
    return result if math.isfinite(result) else None


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

    if any(_finite_number(cf.amount_base) is None for cf in cashflows):
        return None
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
    rate = _finite_number(fx_rates_to_base.get(code))
    if rate is not None and rate > 0:
        return amount * rate
    if isinstance(metadata, dict):
        meta_fx = _finite_number(metadata.get("fx_rate_to_base"))
        if meta_fx is not None and meta_fx > 0:
            return amount * meta_fx
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
    rates: dict[str, float] = {}
    for currency, value in (fx_rates_to_base or {}).items():
        rate = _finite_number(value)
        if rate is not None and rate > 0:
            rates[currency.strip().upper()] = rate
    return rates


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
    activities = effective_activities(activities)
    base = base_currency.strip().upper()
    rates = _normalize_fx_rates(fx_rates_to_base)
    currencies: set[str] = set()
    for act in activities:
        if not isinstance(act, dict) or not _is_posted(act):
            continue
        event_type = _event_type(act)
        if event_type not in _EXTERNAL_FLOW_SIGNS:
            continue
        money = act.get("money")
        if not isinstance(money, dict):
            continue
        amount = money.get("amount")
        currency = money.get("currency")
        if _finite_number(amount) is None:
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
    activities = effective_activities(activities)

    rates = _normalize_fx_rates(fx_rates_to_base)
    flows: list[Cashflow] = []
    warnings: list[str] = []
    for act in activities:
        if not isinstance(act, dict):
            continue
        if not _is_posted(act):
            continue
        event_type = _event_type(act)
        sign = _EXTERNAL_FLOW_SIGNS.get(event_type)
        if sign is None:
            continue
        when_raw = act.get("effective_at")
        if not isinstance(when_raw, str):
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' missing effective_at; cashflow skipped"
            )
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
        money = act.get("money")
        amount = money.get("amount") if isinstance(money, dict) else None
        currency = money.get("currency") if isinstance(money, dict) else None
        if _finite_number(amount) is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has invalid financial amount; cashflow skipped"
            )
            continue
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' missing valid currency; cashflow skipped"
            )
            continue
        base_amount = _resolve_to_base(
            abs(float(amount)),
            currency,
            base_currency,
            metadata=act.get("metadata"),
            fx_rates_to_base=rates,
        )
        if base_amount is not None and not math.isfinite(base_amount):
            warnings.append(
                "Invalid financial amount after FX conversion; cashflow skipped"
            )
            continue
        if base_amount is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' missing FX rate "
                f"for {currency!r} -> {base_currency!r}; cashflow skipped"
            )
            continue
        if currency.strip().upper() != base_currency:
            warnings.append(
                "Foreign cashflow uses undated FX approximation; historical return is approximate"
            )
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
    return _finite_number(totals.get("portfolio_value_base"))


def _snap_by_account(snap: dict[str, Any]) -> dict[str, float | None] | None:
    totals = snap.get("totals")
    if not isinstance(totals, dict):
        return None
    by_account = totals.get("by_account")
    if not isinstance(by_account, dict):
        return None
    out: dict[str, float | None] = {}
    for k, v in by_account.items():
        if not isinstance(k, str):
            continue
        out[k] = _finite_number(v)
    return out


UNASSIGNED_ACCOUNT = "__unassigned__"


@dataclass
class AccountPerformance:
    account_id: str
    start_value_base: float | None
    end_value_base: float | None
    net_external_cashflow_base: float | None
    twr_pct: float | None
    mwr_pct: float | None
    cashflow_count: int
    warnings: list[str] = field(default_factory=list)


def _snap_by_strategic_bucket(snap: dict[str, Any]) -> dict[str, float | None]:
    totals = snap.get("totals")
    if not isinstance(totals, dict):
        return {}
    by_bucket = totals.get("by_strategic_bucket")
    if not isinstance(by_bucket, dict):
        return {}
    out: dict[str, float | None] = {}
    for k, v in by_bucket.items():
        if not isinstance(k, str):
            continue
        out[k] = _finite_number(v)
    return out


def _build_holding_bucket_index(
    portfolio: dict[str, Any] | None,
    policy: dict[str, Any] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Map ``holding_id`` → strategic bucket key (asset_class targets only).

    Other dimensions (region/currency/...) are out of scope for cashflow
    attribution — a single buy/sell rarely lands on a single look-through
    bucket. Holdings whose asset_class isn't covered by any asset_class
    target are mapped to ``__unallocated__`` and returned as warning metadata
    in the second return value (``holding_id`` → ``asset_class``).
    """

    if not isinstance(portfolio, dict) or not isinstance(policy, dict):
        return {}, {}
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
    unallocated_classes: dict[str, str] = {}
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
            if cls:
                unallocated_classes[hid] = cls
    return out, unallocated_classes


def _attribute_external_cashflows_by_strategic_bucket(
    activities: list[dict[str, Any]],
    base_currency: str,
    *,
    fx_rates_to_base: dict[str, float] | None,
    period_start: datetime,
    period_end: datetime,
    holding_to_bucket: dict[str, str],
    unallocated_holding_classes: dict[str, str],
) -> tuple[dict[str, list[Cashflow]], list[str], set[str]]:
    rates = _normalize_fx_rates(fx_rates_to_base)
    buckets: dict[str, list[Cashflow]] = {}
    warnings: list[str] = []
    invalid_scopes: set[str] = set()
    for act in activities:
        if not isinstance(act, dict) or not _is_posted(act):
            continue
        event_type = _event_type(act)
        sign = _EXTERNAL_FLOW_SIGNS.get(event_type)
        if sign is None:
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
        if when < period_start or when > period_end:
            continue
        hid = act.get("holding_id")
        bucket_key: str
        if isinstance(hid, str) and hid in holding_to_bucket:
            bucket_key = holding_to_bucket[hid]
            if bucket_key == "__unallocated__" and hid in unallocated_holding_classes:
                warnings.append(
                    f"Activity '{act.get('id', 'unknown')}' holding '{hid}' "
                    f"asset_class {unallocated_holding_classes[hid]!r} is not covered "
                    "by any asset_class target; attributed to '__unallocated__' "
                    "for per-bucket performance"
                )
        else:
            bucket_key = "__unallocated__"
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has no holding_id "
                "(or holding not found); attributed to '__unallocated__' "
                "for per-bucket performance"
            )
        money = act.get("money")
        amount = money.get("amount") if isinstance(money, dict) else None
        currency = money.get("currency") if isinstance(money, dict) else None
        if _finite_number(amount) is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has invalid financial amount; scope '{bucket_key}' return unavailable"
            )
            invalid_scopes.add(bucket_key)
            continue
        if not isinstance(currency, str) or not currency.strip():
            continue
        base_amount = _resolve_to_base(
            abs(float(amount)),
            currency,
            base_currency,
            metadata=act.get("metadata"),
            fx_rates_to_base=rates,
        )
        if base_amount is not None and _finite_number(base_amount) is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has invalid financial amount after FX conversion; scope '{bucket_key}' return unavailable"
            )
            invalid_scopes.add(bucket_key)
            continue
        if base_amount is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' missing FX rate "
                f"for {currency!r} -> {base_currency!r}; cashflow skipped"
            )
            continue

        buckets.setdefault(bucket_key, []).append(
            Cashflow(when=when, amount_base=sign * base_amount)
        )
    for flows in buckets.values():
        flows.sort(key=lambda cf: cf.when)
    return buckets, warnings, invalid_scopes


@dataclass
class StrategicBucketPerformance:
    bucket_key: str
    start_value_base: float | None
    end_value_base: float | None
    net_external_cashflow_base: float | None
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
    activities = effective_activities(activities)

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

    holding_to_bucket, unallocated_holding_classes = _build_holding_bucket_index(
        portfolio, policy
    )
    cashflows_by_bucket, attribution_warnings, invalid_flow_scopes = (
        _attribute_external_cashflows_by_strategic_bucket(
            activities,
            base_currency,
            fx_rates_to_base=fx_rates_to_base,
            period_start=start_ts,
            period_end=end_ts,
            holding_to_bucket=holding_to_bucket,
            unallocated_holding_classes=unallocated_holding_classes,
        )
    )
    top_warnings.extend(attribution_warnings)

    bucket_keys = sorted(
        set(start_buckets)
        | set(end_buckets)
        | set(cashflows_by_bucket)
        | invalid_flow_scopes
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
        if key != "__unallocated__" and not key.startswith("asset_class:") and flows:
            bucket_warnings.append(
                "Cashflow attribution is only computed for asset_class targets"
            )

        if start_value is None or end_value is None:
            bucket_warnings.append(
                "Invalid bookend financial value; scope return unavailable"
            )
        if key in invalid_flow_scopes:
            bucket_warnings.append(
                "Invalid external cashflow amount; scope return unavailable"
            )
        if start_value is None or end_value is None or key in invalid_flow_scopes:
            twr_fraction = mwr_fraction = None
        else:
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

        net_flow = (
            None
            if key in invalid_flow_scopes
            else _finite_number(sum(cf.amount_base for cf in flows))
        )
        results.append(
            StrategicBucketPerformance(
                bucket_key=key,
                start_value_base=(start_value),
                end_value_base=(end_value),
                net_external_cashflow_base=(net_flow),
                twr_pct=_return_percent(twr_fraction),
                mwr_pct=_return_percent(mwr_fraction),
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
) -> tuple[dict[str, list[Cashflow]], list[str], set[str]]:
    """Bucket external cashflows by ``activity.account_id``.

    Activities without an ``account_id`` land under ``UNASSIGNED_ACCOUNT``
    so the attribution is conservative — callers can warn on that bucket
    if the policy implies every flow should belong to an account.
    """

    rates = _normalize_fx_rates(fx_rates_to_base)
    buckets: dict[str, list[Cashflow]] = {}
    warnings: list[str] = []
    invalid_scopes: set[str] = set()
    for act in activities:
        if not isinstance(act, dict) or not _is_posted(act):
            continue
        event_type = _event_type(act)
        sign = _EXTERNAL_FLOW_SIGNS.get(event_type)
        if sign is None:
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
        if when < period_start or when > period_end:
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
        money = act.get("money")
        amount = money.get("amount") if isinstance(money, dict) else None
        currency = money.get("currency") if isinstance(money, dict) else None
        if _finite_number(amount) is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has invalid financial amount; scope '{account_key}' return unavailable"
            )
            invalid_scopes.add(account_key)
            continue
        if not isinstance(currency, str) or not currency.strip():
            continue
        base_amount = _resolve_to_base(
            abs(float(amount)),
            currency,
            base_currency,
            metadata=act.get("metadata"),
            fx_rates_to_base=rates,
        )
        if base_amount is not None and _finite_number(base_amount) is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' has invalid financial amount after FX conversion; scope '{account_key}' return unavailable"
            )
            invalid_scopes.add(account_key)
            continue
        if base_amount is None:
            warnings.append(
                f"Activity '{act.get('id', 'unknown')}' missing FX rate "
                f"for {currency!r} -> {base_currency!r}; cashflow skipped"
            )
            continue

        buckets.setdefault(account_key, []).append(
            Cashflow(when=when, amount_base=sign * base_amount)
        )
    for flows in buckets.values():
        flows.sort(key=lambda cf: cf.when)
    return buckets, warnings, invalid_scopes


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
    activities = effective_activities(activities)

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
    if start_by_account is None:
        top_warnings.append(
            "Start snapshot is missing totals.by_account; per-account TWR unavailable"
        )
    if end_by_account is None:
        top_warnings.append(
            "End snapshot is missing totals.by_account; per-account TWR unavailable"
        )
    if start_by_account is None or end_by_account is None:
        return [], top_warnings

    cashflows_by_account, attribution_warnings, invalid_flow_scopes = (
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
        | invalid_flow_scopes
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

        if start_value is None or end_value is None:
            warnings.append("Invalid bookend financial value; scope return unavailable")
        if aid in invalid_flow_scopes:
            warnings.append(
                "Invalid external cashflow amount; scope return unavailable"
            )
        if start_value is None or end_value is None or aid in invalid_flow_scopes:
            twr_fraction = mwr_fraction = None
        else:
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

        net_flow = (
            None
            if aid in invalid_flow_scopes
            else _finite_number(sum(cf.amount_base for cf in flows))
        )
        results.append(
            AccountPerformance(
                account_id=aid,
                start_value_base=(start_value),
                end_value_base=(end_value),
                net_external_cashflow_base=(net_flow),
                twr_pct=_return_percent(twr_fraction),
                mwr_pct=_return_percent(mwr_fraction),
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
    flow_valuations: dict[str, Any] | None = None,
) -> PerformanceResult:
    evidence = (
        parse_flow_valuations(flow_valuations, base_currency)
        if flow_valuations is not None
        else None
    )
    activities = effective_activities(activities)
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
            "Snapshot has missing or nonfinite portfolio_value_base; cannot compute return"
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
    # Transfers have no stable pairing identity in the current contract. Keep
    # the legacy external-flow treatment and disclose the unresolved boundary.
    for activity in activities:
        if not isinstance(activity, dict) or not _is_posted(activity):
            continue
        if _event_type(activity) not in {"transfer_in", "transfer_out"}:
            continue
        when_raw = activity.get("effective_at")
        if not isinstance(when_raw, str):
            continue  # The extractor already disclosed the invalid timestamp.
        try:
            when = _parse_iso(when_raw)
        except (TypeError, ValueError):
            continue
        if start_ts <= when <= end_ts:
            cf_warnings.append(
                "Transfer identity unresolved: no supported internal-transfer pairing convention; treated as external, approximate"
            )
            break
    for snapshot in (start_snap, end_snap):
        currency = snapshot.get("base_currency")
        if currency is None:
            cf_warnings.append(
                "Snapshot has no base_currency; valuation currency is unverified and approximate"
            )
        elif currency != base_currency:
            cf_warnings.append(
                "Invalid financial input: snapshot base_currency does not match portfolio base currency"
            )
    warnings.extend(cf_warnings)

    twr_fraction = modified_dietz(start_value, end_value, cashflows, start_ts, end_ts)

    xirr_series = [Cashflow(when=start_ts, amount_base=-start_value)]
    for cf in cashflows:
        xirr_series.append(Cashflow(when=cf.when, amount_base=-cf.amount_base))
    xirr_series.append(Cashflow(when=end_ts, amount_base=end_value))
    mwr_fraction = xirr(xirr_series)
    if any("invalid financial" in warning.lower() for warning in cf_warnings):
        twr_fraction = mwr_fraction = None
    selected, method, fallback_reason = _select_twr(
        start_value,
        end_value,
        cashflows,
        start_ts,
        end_ts,
        evidence,
        cf_warnings,
        twr_fraction,
    )
    selected_pct = _return_percent(selected)
    if selected is not None and selected_pct is None:
        method, fallback_reason = (
            "unavailable",
            "Return percentage exceeds the finite supported range",
        )
    if fallback_reason:
        warnings.append(f"TWR {method}: {fallback_reason}")

    net_flow = _finite_number(sum(cf.amount_base for cf in cashflows))

    twr_pct = _return_percent(twr_fraction)
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
        start_value_base=(start_value),
        end_value_base=(end_value),
        net_external_cashflow_base=(net_flow),
        twr_pct=twr_pct,
        mwr_pct=_return_percent(mwr_fraction),
        cashflow_count=len(cashflows),
        warnings=warnings,
        benchmarks=benchmark_comparisons,
        twr_method=method,
        twr_return_pct=selected_pct,
        linked_twr_pct=selected_pct if method == "linked_subperiod" else None,
        twr_fallback_reason=fallback_reason,
    )
