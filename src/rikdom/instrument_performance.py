"""Investor cashflow returns for one holding, in its transaction currency.

The ledger supplies acquisition cash, never tax-lot or current cost basis. Full
returns require explicit complete history and a dated terminal valuation. The
observed cash totals remain useful when those requirements cannot be verified.
No FX conversion or hypothetical liquidation taxes are applied.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
import math
from typing import Any

from .performance import Cashflow, xirr
from .activities import check_financial_contract, effective_activities
from .income import income_amount_basis


_DISTRIBUTIONS = {"dividend", "interest", "income", "amortization", "reimbursement"}
_CASH_EVENTS = _DISTRIBUTIONS | {"buy", "sell", "fee", "tax_withheld"}


def _date(value: Any, *, end_of_day: bool = False) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing date")
    value = value.strip()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if end_of_day and len(value) == 10:
        return datetime.combine(parsed.date(), time.max, tzinfo=timezone.utc)
    return parsed


def _number(value: Any) -> Decimal:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("Amount must be a finite number")
    return Decimal(str(value))


def _money(value: Any, currency: str | None = None, *, signed: bool = False) -> tuple[Decimal, str]:
    if not isinstance(value, dict):
        raise ValueError("Missing money")
    amount = _number(value.get("amount"))
    code = value.get("currency")
    if (
        not isinstance(code, str)
        or len(code.strip()) != 3
        or not code.strip().isascii()
        or not code.strip().isalpha()
    ):
        raise ValueError("Invalid currency")
    code = code.strip().upper()
    if currency is not None and code != currency:
        raise ValueError(
            f"Currency {code} differs from {currency}; no FX conversion applied"
        )
    if amount < 0 and not signed:
        raise ValueError("Money and costs must be nonnegative")
    return amount, code


def _tickers(holding: dict[str, Any]) -> set[str]:
    identifiers = holding.get("identifiers") or {}
    ticker = identifiers.get("ticker") if isinstance(identifiers, dict) else None
    values = [ticker]
    metadata = holding.get("metadata") or {}
    aliases = metadata.get("instrument_aliases") if isinstance(metadata, dict) else None
    if isinstance(aliases, list):
        values.extend(aliases)
    return {
        value.strip().upper()
        for value in values
        if isinstance(value, str) and value.strip()
    }


def _has_movement(activity: dict[str, Any], *, include_quantity: bool = True) -> bool:
    amounts = [
        _money(activity[key])[0]
        for key in ("money", "fees", "withholding_tax")
        if key in activity
    ]
    if include_quantity and "quantity" in activity:
        amounts.append(_number(activity["quantity"]))
    return any(amount != 0 for amount in amounts)


def _quantity_delta(activity: dict[str, Any], holding_id: str) -> Decimal:
    action = activity.get("corporate_action")
    if "corporate_action" in activity and (
        not isinstance(action, dict) or not isinstance(action.get("legs"), list)
    ):
        raise ValueError("Invalid corporate_action legs")
    if isinstance(action, dict) and isinstance(action.get("legs"), list):
        legs = [
            leg
            for leg in action["legs"]
            if isinstance(leg, dict) and leg.get("holding_id") == holding_id
        ]
        if legs:
            return sum((_number(leg.get("quantity_delta")) for leg in legs), Decimal(0))
    event = activity.get("event_type")
    quantity = _number(activity.get("quantity"))
    if event == "sell":
        return -abs(quantity)
    if event == "buy":
        if quantity <= 0:
            raise ValueError("Acquisition quantity must be positive")
        return quantity
    if event == "split":
        return quantity  # Existing ledger convention: signed additional units.
    raise ValueError("Corporate action needs a quantity_delta leg for this holding")


def compute_instrument_performance(
    portfolio: dict,
    holding_id: str,
    *,
    until: str | None = None,
    terminal_value: float | None = None,
    terminal_at: str | None = None,
) -> dict:
    """Return auditable observed cashflows and, with complete history, XIRR.

    ``terminal_value`` is an explicit valuation in the holding's currency and
    requires ``terminal_at`` or ``until``. Otherwise the current market value
    is usable only at ``holding.as_of``. Invalid explicit inputs and unknown
    holding IDs raise ValueError; ledger defects produce incomplete diagnostics.
    """
    check_financial_contract(portfolio)
    holdings = [h for h in portfolio.get("holdings", []) if isinstance(h, dict)]
    matches = [h for h in holdings if h.get("id") == holding_id]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one holding with id {holding_id!r}; found {len(matches)}"
        )
    holding = matches[0]
    identifiers = holding.get("identifiers") or {}
    ticker = identifiers.get("ticker") if isinstance(identifiers, dict) else None
    aliases = _tickers(holding)
    owners = {alias: sum(alias in _tickers(h) for h in holdings) for alias in aliases}
    warnings: list[str] = []
    requested_end = _date(until) if until is not None else None
    requested_bound = _date(until, end_of_day=True) if until is not None else None
    as_of = None
    try:
        as_of = _date(holding.get("as_of"))
    except ValueError:
        pass

    value: Decimal | None = None
    currency: str | None = None
    basis: str | None = None
    end = requested_end or as_of
    try:
        current_value, currency = _money(holding.get("market_value"))
    except ValueError as exc:
        current_value = None
        if terminal_value is None:
            warnings.append(f"Holding {holding_id}: invalid market_value ({exc})")
    if terminal_value is not None:
        value = _number(terminal_value)
        if value < 0:
            raise ValueError("terminal_value must be nonnegative")
        if terminal_at is None and until is None:
            raise ValueError("terminal_value requires terminal_at or until")
        end = _date(terminal_at or until)
        if requested_end is not None and (
            end > requested_bound
            or end.date() != requested_end.date()
            or (len(until.strip()) != 10 and end != requested_end)
        ):
            raise ValueError("terminal_at must coincide with the requested until date")
        basis = "explicit_terminal_value"
    elif terminal_at is not None:
        raise ValueError("terminal_at requires terminal_value")
    elif as_of is None:
        warnings.append(
            "A dated holding.as_of is required for the terminal market value"
        )
    elif requested_end is not None and (
        as_of.date() != requested_end.date()
        or (len(until.strip()) != 10 and as_of != requested_end)
    ):
        warnings.append(
            "Requested date differs from holding.as_of; supply a dated terminal_value"
        )
    else:
        end = as_of
        value = current_value
        basis = "gross_market_value" if value is not None else None

    cutoff = (
        min(requested_bound, end)
        if requested_bound is not None and end is not None
        else requested_bound or end
    )
    observed = {
        key: Decimal(0)
        for key in (
            "observed_buy_outflows",
            "observed_sell_inflows",
            "observed_distributions",
            "observed_fees",
            "observed_taxes",
            "observed_net_cashflow",
        )
    }
    rows: list[tuple[datetime, dict]] = []
    buys: list[datetime] = []
    quantity_rows: list[tuple[datetime, Decimal]] = []
    quantity_valid = True
    quantity_after_cutoff_on_valuation_day = False
    seen: dict[str, dict] = {}
    seen_imports: dict[str, dict] = {}
    for activity in effective_activities(portfolio.get("activities") or []):
        if not isinstance(activity, dict):
            continue
        status = activity.get("status", "posted")
        if not isinstance(status, str) or status.strip().lower() not in ("", "posted"):
            continue
        action = activity.get("corporate_action")
        legs = action.get("legs", []) if isinstance(action, dict) else []
        if not isinstance(legs, list):
            legs = []
        own_leg = any(
            isinstance(leg, dict) and leg.get("holding_id") == holding_id
            for leg in legs
        )
        reference = activity.get("holding_id")
        instrument = activity.get("instrument") or {}
        act_ticker = instrument.get("ticker") if isinstance(instrument, dict) else None
        act_ticker = act_ticker.strip().upper() if isinstance(act_ticker, str) else None
        if not own_leg and reference != holding_id:
            if reference is not None or act_ticker not in aliases:
                continue
        activity_id = activity.get("id")
        try:
            when = _date(
                activity.get("settled_at")
                if "settled_at" in activity
                else activity.get("effective_at")
            )
        except ValueError:
            warnings.append(f"Activity {activity_id}: invalid cash date; skipped")
            continue
        if cutoff is not None and when > cutoff:
            if (
                as_of is not None
                and when <= as_of
                and cutoff.date() == as_of.date()
                and (
                    activity.get("event_type") in ("buy", "sell", "split", "merger")
                    or own_leg
                )
            ):
                quantity_after_cutoff_on_valuation_day = True
            continue
        if not own_leg and reference != holding_id and owners[act_ticker] != 1:
            warnings.append(
                f"Activity {activity_id}: ambiguous ticker {act_ticker}; skipped"
            )
            continue
        if isinstance(activity_id, str) and activity_id in seen:
            if activity != seen[activity_id]:
                warnings.append(
                    f"Activity {activity_id}: conflicting duplicate id; skipped"
                )
            continue
        if isinstance(activity_id, str):
            seen[activity_id] = activity
        import_key = activity.get("idempotency_key")
        if isinstance(import_key, str) and import_key:
            imported_content = {
                key: val
                for key, val in activity.items()
                if key not in ("id", "import_run_id", "ingested_at", "provenance")
            }
            if import_key in seen_imports:
                if imported_content != seen_imports[import_key]:
                    warnings.append(
                        f"Activity {activity_id}: conflicting idempotency_key; skipped"
                    )
                continue
            seen_imports[import_key] = imported_content
        event = str(activity.get("event_type", "")).strip().lower()
        if isinstance(action, dict):
            try:
                if any(
                    isinstance(leg, dict)
                    and leg.get("holding_id") != holding_id
                    and _number(leg.get("quantity_delta")) != 0
                    for leg in legs
                ):
                    warnings.append(
                        f"Activity {activity_id}: cross-holding corporate action requires "
                        "reconciled predecessor cash lineage; full return unavailable"
                    )
            except ValueError:
                warnings.append(
                    f"Activity {activity_id}: invalid related corporate action quantity"
                )
        corporate_event = event in ("split", "merger") or (event == "other" and own_leg)
        if event in ("buy", "sell") or corporate_event:
            try:
                quantity_rows.append((when, _quantity_delta(activity, holding_id)))
            except ValueError as exc:
                quantity_valid = False
                warnings.append(
                    f"Activity {activity_id}: cannot reconstruct quantity ({exc})"
                )
        if corporate_event:
            try:
                if _has_movement(activity, include_quantity=False):
                    warnings.append(
                        f"Activity {activity_id}: corporate action cash component is unhandled"
                    )
            except ValueError as exc:
                warnings.append(
                    f"Activity {activity_id}: invalid corporate action money ({exc})"
                )
            continue
        if event not in _CASH_EVENTS:
            try:
                if _has_movement(activity):
                    warnings.append(
                        f"Activity {activity_id}: unhandled {event!r} movement; history incomplete"
                    )
            except ValueError as exc:
                warnings.append(
                    f"Activity {activity_id}: invalid unhandled {event!r} movement ({exc})"
                )
            continue
        try:
            income_basis = income_amount_basis(activity) if event in _DISTRIBUTIONS else "gross"
            if income_basis == "unknown":
                raise ValueError("Income amount basis is unknown; investor receipts unavailable")
            net_distribution = event in _DISTRIBUTIONS and income_basis == "net"
            amount, code = _money(activity.get("money"), currency, signed=net_distribution)
            if currency is None:
                currency = code
            costs = {}
            for field in ("fees", "withholding_tax"):
                try:
                    costs[field] = (
                        _money(activity[field], currency, signed=net_distribution)[0]
                        if field in activity else Decimal(0)
                    )
                except ValueError as exc:
                    if not net_distribution:
                        raise
                    costs[field] = Decimal(0)
                    warnings.append(
                        f"Activity {activity_id}: known net receipt retained; "
                        f"{field} breakdown unavailable ({exc})"
                    )
            fees, taxes = costs["fees"], costs["withholding_tax"]
        except ValueError as exc:
            warnings.append(f"Activity {activity_id}: invalid money ({exc}); skipped")
            continue
        observed["observed_fees"] += fees
        observed["observed_taxes"] += taxes
        if event == "buy":
            cash = -(amount + fees + taxes)
            observed["observed_buy_outflows"] -= cash
            buys.append(when)
        elif event == "sell":
            cash = amount - fees - taxes
            observed["observed_sell_inflows"] += cash
        elif event in _DISTRIBUTIONS:
            cash = amount if income_basis == "net" else amount - fees - taxes
            observed["observed_distributions"] += cash
        else:
            cash = -(amount + fees + taxes)
            observed["observed_fees" if event == "fee" else "observed_taxes"] += amount
        observed["observed_net_cashflow"] += cash
        rows.append(
            (
                when,
                {
                    "effective_at": when.isoformat(),
                    "amount": float(cash),
                    "event_type": event,
                    "activity_id": activity_id,
                },
            )
        )

    start = min(buys) if buys else None
    extension = holding.get("extensions") or {}
    history = (
        extension.get("rikdom_instrument_history")
        if isinstance(extension, dict)
        else None
    )
    if not isinstance(history, dict) or history.get("status") != "complete":
        warnings.append(
            "Explicit complete instrument history is required for since-purchase returns"
        )
    else:
        try:
            coverage_start = _date(history.get("from"))
            coverage_end = _date(history.get("through"), end_of_day=True)
            if (
                start is None
                or end is None
                or coverage_start > start
                or coverage_end < end
            ):
                warnings.append(
                    "Instrument history does not cover first acquisition through valuation"
                )
        except ValueError:
            warnings.append("Instrument history has invalid coverage dates")
        if history.get("missing_periods"):
            warnings.append("Instrument history declares missing periods")
    if start is None:
        warnings.append(
            "No valid acquisition cashflows; tax lots cannot establish inception"
        )
    elif any(when < start for when, _ in rows):
        warnings.append(
            "Observed investor cashflow predates first acquisition; inception is incomplete"
        )
    if observed["observed_buy_outflows"] <= 0:
        warnings.append(
            "Acquisition cashflows do not establish positive invested capital"
        )
    if end is None or value is None:
        warnings.append("A terminal valuation at the requested date is unavailable")
    if currency is None:
        warnings.append("Transaction currency is unavailable; no currency is assumed")
    quantity = Decimal(0)
    for _, delta in sorted(quantity_rows, key=lambda row: row[0]):
        quantity += delta
        if quantity < Decimal("-0.00000001"):
            warnings.append(
                "Quantity ledger becomes negative; acquisition history is incomplete"
            )
            break
    if (
        quantity_valid
        and "quantity" in holding
        and as_of is not None
        and cutoff is not None
        and (cutoff >= as_of or cutoff.date() == as_of.date())
    ):
        try:
            if quantity_after_cutoff_on_valuation_day:
                warnings.append(
                    "Intraday terminal value predates quantity changes in holding.as_of; quantity cannot be reconciled"
                )
            quantity = sum(
                (delta for when, delta in quantity_rows if when <= as_of), Decimal(0)
            )
            expected_quantity = _number(holding["quantity"])
            if abs(quantity - expected_quantity) > Decimal("0.00000001"):
                warnings.append(
                    f"Reconstructed quantity {quantity} differs from holding.quantity {expected_quantity}"
                )
        except ValueError:
            warnings.append("Holding quantity is invalid")

    rows.sort(key=lambda row: row[0])
    if value is not None and end is not None:
        rows.append(
            (
                end,
                {
                    "effective_at": end.isoformat(),
                    "amount": float(value),
                    "event_type": "terminal_value",
                    "activity_id": None,
                },
            )
        )
        rows.sort(key=lambda row: row[0])
    complete = not warnings
    rate = (
        xirr([Cashflow(when, row["amount"]) for when, row in rows])
        if complete and start is not None and end is not None and end > start
        else None
    )
    return {
        "holding_id": holding_id,
        "ticker": ticker,
        "currency": currency,
        "status": "complete" if complete else "incomplete_history",
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "terminal_value": float(value) if value is not None else None,
        "valuation_basis": basis,
        **{key: float(amount) for key, amount in observed.items()},
        "profit_amount": float(value + observed["observed_net_cashflow"])
        if complete
        else None,
        "xirr_pct": rate * 100 if rate is not None and math.isfinite(rate) else None,
        "cashflows": [row for _, row in rows],
        "warnings": warnings,
    }
