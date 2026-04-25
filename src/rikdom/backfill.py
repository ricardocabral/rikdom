"""Backfill helpers for economic_exposure and fixed-income cash_flows.

These produce *synthetic* fallbacks so coverage gaps surface explicitly:
- exposure stubs are tagged classification_source='heuristic', confidence='low'
- cash flow legs are tagged status='PROJECTED' with notes='synthesized:...'

Both operations are idempotent: holdings that already carry data are left
untouched unless --force is requested.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


_FREQ_TO_MONTHS = {
    "MONTHLY": 1,
    "QUARTERLY": 3,
    "SEMIANNUAL": 6,
    "ANNUAL": 12,
}


@dataclass
class BackfillReport:
    touched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _catalog_exposure_index(catalog: list[Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(catalog, list):
        return index
    for item in catalog:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("id", "")).strip()
        exposure = item.get("economic_exposure")
        if type_id and isinstance(exposure, dict):
            index[type_id] = exposure
    return index


def _catalog_class_index(catalog: list[Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    if not isinstance(catalog, list):
        return index
    for item in catalog:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("id", "")).strip()
        asset_class = str(item.get("asset_class", "")).strip()
        if type_id and asset_class:
            index[type_id] = asset_class
    return index


def backfill_exposure(
    portfolio: dict[str, Any],
    *,
    include_catalog: bool = False,
    today: date | None = None,
) -> tuple[dict[str, Any], BackfillReport]:
    """Synthesize a single-line economic_exposure stub for holdings missing one.

    Precedence:
      - If holding already has economic_exposure, skip.
      - Else if asset_type catalog has economic_exposure and include_catalog=False, skip
        (the look-through code already inherits via catalog).
      - Else write {breakdown:[{weight_pct:100, asset_class:<catalog.asset_class>}]}.

    The catalog fallback path is opt-in because most callers want gaps to remain
    visible at the catalog level, and applying a stub there would erase that signal.
    """

    new = copy.deepcopy(portfolio)
    report = BackfillReport()
    catalog = new.get("asset_type_catalog", []) or []
    catalog_exposures = _catalog_exposure_index(catalog)
    catalog_classes = _catalog_class_index(catalog)
    as_of = (today or date.today()).isoformat()

    holdings = new.get("holdings", []) or []
    for i, holding in enumerate(holdings):
        if not isinstance(holding, dict):
            continue
        hid = str(holding.get("id", f"index-{i}"))
        if isinstance(holding.get("economic_exposure"), dict):
            report.skipped.append(f"{hid}: already has economic_exposure")
            continue

        type_id = str(holding.get("asset_type_id", "")).strip()
        if type_id in catalog_exposures and not include_catalog:
            report.skipped.append(
                f"{hid}: asset_type '{type_id}' carries catalog economic_exposure"
            )
            continue

        asset_class = catalog_classes.get(type_id)
        if not asset_class:
            report.warnings.append(
                f"{hid}: cannot synthesize stub — asset_type '{type_id}' has no asset_class"
            )
            continue

        holding["economic_exposure"] = {
            "breakdown": [{"weight_pct": 100, "asset_class": asset_class}],
            "classification_source": "heuristic",
            "confidence": "low",
            "as_of": as_of,
            "notes": "backfilled fallback from asset_type.asset_class",
        }
        report.touched.append(hid)

    return new, report


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _add_months(anchor: date, months: int) -> date:
    month = anchor.month - 1 + months
    year = anchor.year + month // 12
    month = month % 12 + 1
    day = min(anchor.day, _last_day_of_month(year, month))
    return date(year, month, day)


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days + (date(year, month, 1).day - 1)


def _generate_coupon_dates(
    start: date, maturity: date, period_months: int, first: date | None
) -> list[date]:
    dates: list[date] = []
    cursor = first or _add_months(start, period_months)
    while cursor <= maturity:
        dates.append(cursor)
        cursor = _add_months(cursor, period_months)
    if not dates or dates[-1] != maturity:
        dates.append(maturity)
    return dates


def _resolve_face_amount(holding: dict[str, Any]) -> tuple[float | None, str | None, str]:
    """Return (face, currency, source). Falls back to market_value as a low-fidelity proxy."""
    attrs = holding.get("instrument_attributes")
    if isinstance(attrs, dict):
        for key in ("face_value", "notional", "principal"):
            value = attrs.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                mv = holding.get("market_value")
                currency = mv.get("currency") if isinstance(mv, dict) else None
                if isinstance(currency, str):
                    return float(value), currency, f"instrument_attributes.{key}"
    mv = holding.get("market_value")
    if isinstance(mv, dict):
        amount = mv.get("amount")
        currency = mv.get("currency")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool) and isinstance(currency, str):
            return float(amount), currency, "fallback:market_value"
    return None, None, "missing"


def backfill_cashflows(
    portfolio: dict[str, Any],
    *,
    today: date | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], BackfillReport]:
    """Synthesize PROJECTED interest legs + terminal principal for fixed-rate debt.

    Skips holdings that already have non-empty fixed_income_profile.cash_flows
    unless force=True. Only handles FIXED coupons with a known payment_frequency,
    accrual_start_date (or first_coupon_date), maturity_date, and fixed_rate_pct.
    """

    new = copy.deepcopy(portfolio)
    report = BackfillReport()
    today = today or date.today()

    for i, holding in enumerate(new.get("holdings", []) or []):
        if not isinstance(holding, dict):
            continue
        hid = str(holding.get("id", f"index-{i}"))
        profile = holding.get("fixed_income_profile")
        if not isinstance(profile, dict):
            continue
        coupon = profile.get("coupon")
        if not isinstance(coupon, dict):
            report.skipped.append(f"{hid}: no fixed_income_profile.coupon")
            continue

        existing = profile.get("cash_flows")
        if isinstance(existing, list) and existing and not force:
            report.skipped.append(f"{hid}: cash_flows already present")
            continue

        if str(coupon.get("coupon_type", "")).upper() != "FIXED":
            report.skipped.append(f"{hid}: coupon_type is not FIXED")
            continue

        rate = coupon.get("fixed_rate_pct")
        if not isinstance(rate, (int, float)) or isinstance(rate, bool):
            report.warnings.append(f"{hid}: missing coupon.fixed_rate_pct")
            continue

        frequency = str(coupon.get("payment_frequency", "")).upper()
        period_months = _FREQ_TO_MONTHS.get(frequency)
        if period_months is None:
            report.skipped.append(f"{hid}: unsupported payment_frequency '{frequency}'")
            continue

        maturity = _parse_iso_date(profile.get("maturity_date"))
        accrual_start = _parse_iso_date(coupon.get("accrual_start_date"))
        first_coupon = _parse_iso_date(coupon.get("first_coupon_date"))
        if maturity is None or (accrual_start is None and first_coupon is None):
            report.warnings.append(
                f"{hid}: cannot project — need maturity_date and one of accrual_start_date/first_coupon_date"
            )
            continue

        face, currency, source = _resolve_face_amount(holding)
        if face is None or currency is None:
            report.warnings.append(f"{hid}: cannot resolve face value")
            continue

        coupon_dates = _generate_coupon_dates(
            accrual_start or first_coupon,
            maturity,
            period_months,
            first_coupon,
        )
        periodic_amount = round(face * (float(rate) / 100.0) * (period_months / 12.0), 2)

        legs: list[dict[str, Any]] = []
        for d in coupon_dates:
            if d > maturity:
                break
            legs.append(
                {
                    "date": d.isoformat(),
                    "kind": "INTEREST",
                    "amount": {"amount": periodic_amount, "currency": currency},
                    "status": "PROJECTED",
                    "rate_pct": float(rate),
                    "notes": f"synthesized:face={source}",
                }
            )
        legs.append(
            {
                "date": maturity.isoformat(),
                "kind": "PRINCIPAL",
                "amount": {"amount": round(face, 2), "currency": currency},
                "status": "PROJECTED",
                "notes": f"synthesized:face={source}",
            }
        )
        profile["cash_flows"] = legs
        report.touched.append(hid)

    return new, report
