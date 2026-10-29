"""Read-only period result bridge and conservative reviewed FIFO decomposition.

The bridge is a residual from verified performance bookends and complete external
flows. Optional v1 evidence reconciles opening/closing positions, cash and FIFO
costs. It never treats current holdings or reported profit as historical basis.
FIFO currently supports only reporting-currency cash equities with unadjusted
values; FX, corporate actions and unsupported movements leave it unavailable.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import math
from typing import Any

from .activities import check_financial_contract, effective_activities
from .historical_fx import HistoricalFx
from .income import income_amount_basis
from .performance import PerformanceResult, extract_external_cashflows

_EXTERNAL = {"contribution", "withdrawal", "transfer_in", "transfer_out"}
_INCOME = {"dividend", "interest", "income"}
_TOLERANCE = Decimal("0.00000001")
_COMPONENTS = (
    "realized_gain_base",
    "opening_unrealized_gain_base",
    "closing_unrealized_gain_base",
    "unrealized_change_base",
    "net_income_base",
    "standalone_fees_base",
    "standalone_taxes_base",
    "explained_result_base",
    "reconciliation_difference_base",
)


def load_profit_basis(path: str | Path) -> dict:
    """Read v1 evidence JSON strictly; semantic availability is checked on compute.

    Duplicate keys, NaN/Infinity and numeric overflow are rejected before any
    calculation. A valid JSON object can still be incomplete reviewed evidence.
    """

    def unique(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"profit basis: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def number(raw: str) -> float:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("profit basis: nonfinite JSON number")
        return value

    def reject(raw: str) -> None:
        raise ValueError(f"profit basis: invalid JSON constant {raw}")

    with Path(path).open(encoding="utf-8") as handle:
        result = json.load(
            handle, object_pairs_hook=unique, parse_constant=reject, parse_float=number
        )
    if not isinstance(result, dict):
        raise ValueError("profit basis must be a JSON object")
    return result


def _number(value: Any, *, signed: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a finite financial number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (not signed and value < 0):
        raise ValueError("Expected a finite nonnegative financial number")
    return Decimal(str(value))


def _json(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Financial result exceeds finite JSON range")
    return result


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Expected an ISO timestamp with explicit timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Expected an ISO timestamp with explicit timezone")
    return result.astimezone(timezone.utc)


def _keys(value: Any, keys: set[str], name: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} requires exactly: " + ", ".join(sorted(keys)))
    return value


def _identity(row: dict, currency: str) -> tuple[str, str]:
    if row.get("currency") != currency:
        raise ValueError("FIFO supports reporting-currency positions and costs only")
    key = (row.get("account_id"), row.get("holding_id"))
    if any(not isinstance(part, str) or not part.strip() for part in key):
        raise ValueError("Explicit account_id and holding_id are required")
    return key


def _effective_ledger(portfolio: dict) -> list[dict]:
    check_financial_contract(portfolio)
    activities = portfolio.get("activities", [])
    if not isinstance(activities, list) or any(
        not isinstance(a, dict) for a in activities
    ):
        raise ValueError("activities must be an array of objects")
    selected = []
    ids: dict[str, dict] = {}
    imports: dict[str, dict] = {}
    for activity in effective_activities(activities):
        status = activity.get("status", "posted")
        if not isinstance(status, str):
            raise ValueError("Invalid activity status")
        if status.strip().lower() not in ("posted", ""):
            continue
        aid = activity.get("id")
        if not isinstance(aid, str) or not aid.strip():
            raise ValueError("Every posted activity requires an explicit id")
        if aid in ids:
            if activity != ids[aid]:
                raise ValueError(f"Conflicting duplicate activity id {aid!r}")
            continue
        ids[aid] = activity
        key = activity.get("idempotency_key")
        if key is not None and (not isinstance(key, str) or not key.strip()):
            raise ValueError("Invalid idempotency_key")
        if key:
            content = {
                k: v
                for k, v in activity.items()
                if k not in ("id", "import_run_id", "ingested_at", "provenance")
            }
            if key in imports:
                if content != imports[key]:
                    raise ValueError(f"Conflicting idempotency_key {key!r}")
                continue
            imports[key] = content
        selected.append(activity)
    return selected


def _bridge(
    portfolio: dict,
    performance: PerformanceResult,
    ledger: list[dict],
    historical_fx: HistoricalFx | None,
) -> dict:
    currency = performance.base_currency
    settings = portfolio.get("settings", {})
    declared = settings.get("base_currency") if isinstance(settings, dict) else None
    if (
        declared not in (None, currency)
        or portfolio.get("base_currency", currency) != currency
        or not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isupper()
        or not currency.isalpha()
    ):
        raise ValueError("Portfolio and performance reporting currencies must match")
    start, end = (
        _timestamp(performance.period_start),
        _timestamp(performance.period_end),
    )
    if performance.fx_status == "unavailable":
        raise ValueError("Performance external-flow FX is explicitly unavailable")
    if end <= start:
        raise ValueError("A positive performance window is required")
    opening = _number(performance.start_value_base)
    closing = _number(performance.end_value_base)
    net = _number(performance.net_external_cashflow_base, signed=True)
    # Legacy performance results can retain numeric placeholders after a bad
    # bookend. Reject those explicit diagnostics, while allowing TWR fallback.
    if any(
        "snapshot" in warning.lower()
        and any(
            term in warning.lower()
            for term in ("missing", "nonfinite", "no base_currency", "does not match")
        )
        for warning in performance.warnings
    ):
        raise ValueError(
            "Performance bookend valuation/currency evidence is unavailable"
        )
    flows, warnings = extract_external_cashflows(
        ledger,
        currency,
        historical_fx=historical_fx,
        period_start=start,
        period_end=end,
    )
    if warnings:
        raise ValueError(
            "External cashflow evidence unavailable: " + "; ".join(warnings)
        )
    evidence = []
    for activity in ledger:
        event = str(activity.get("event_type", "")).strip().lower()
        if event not in _EXTERNAL:
            continue
        when = _timestamp(activity.get("effective_at"))
        if not start <= when <= end:
            continue
        if event in ("transfer_in", "transfer_out"):
            raise ValueError(
                "Unresolved transfer identity prevents exact external-flow bridge"
            )
        money = activity["money"]
        amount = _number(money["amount"], signed=True)
        code = money["currency"]
        fx_evidence = None
        rate = Decimal(1)
        if historical_fx is not None:
            lookup = historical_fx.resolve(code, when)
            if lookup.rate is None:
                raise ValueError("Historical external-flow FX is unavailable")
            rate = _number(lookup.rate)
            fx_evidence = copy.deepcopy(lookup.evidence)
        elif code != currency:
            raise ValueError("Undated foreign external-flow FX is unsupported")
        converted = abs(amount) * rate * (-1 if event == "withdrawal" else 1)
        evidence.append(
            {
                "activity_id": activity["id"],
                "event_type": event,
                "effective_at": activity["effective_at"],
                "native_amount": _json(amount),
                "native_currency": code,
                "amount_base": _json(converted),
                "fx_evidence": fx_evidence,
            }
        )
    extracted_net = sum((Decimal(str(flow.amount_base)) for flow in flows), Decimal(0))
    if (
        abs(extracted_net - net) > _TOLERANCE
        or len(flows) != performance.cashflow_count
    ):
        raise ValueError(
            "Effective ledger external flows disagree with performance result"
        )
    result = closing - opening - net
    return {
        "status": "complete",
        "opening_value_base": _json(opening),
        "net_external_cashflow_base": _json(net),
        "investment_result_base": _json(result),
        "closing_value_base": _json(closing),
        "equation": "opening + net_external_flows + investment_result = closing",
        "provenance": "computed_from_performance_bookends_and_effective_ledger",
        "cashflow_evidence": evidence,
    }


def _fifo_decomposition(
    basis: dict, ledger: list[dict], performance: PerformanceResult, bridge: dict
) -> dict:
    fields = {
        "contract_version",
        "scope",
        "base_currency",
        "period_start",
        "period_end",
        "method",
        "price_adjustment",
        "cost_convention",
        "review",
        "history",
        "opening_cash_base",
        "closing_cash_base",
        "opening_lots",
        "opening_positions",
        "closing_positions",
    }
    _keys(basis, fields, "profit basis")
    constants = {
        "contract_version": "1.0",
        "scope": "portfolio",
        "base_currency": performance.base_currency,
        "method": "fifo",
        "price_adjustment": "unadjusted",
        "cost_convention": "buy_costs_capitalized_sell_costs_deducted",
    }
    if any(basis[key] != value for key, value in constants.items()):
        raise ValueError(
            "Unsupported basis version, scope, currency, method or adjustment/cost convention"
        )
    start, end = (
        _timestamp(performance.period_start),
        _timestamp(performance.period_end),
    )
    if (
        _timestamp(basis["period_start"]) != start
        or _timestamp(basis["period_end"]) != end
    ):
        raise ValueError("Basis period must equal the performance bookend instants")
    review = _keys(
        basis["review"],
        {"status", "source", "reviewed_at", "retrieved_before"},
        "review",
    )
    if (
        review["status"] != "reviewed"
        or not isinstance(review["source"], str)
        or not review["source"].strip()
    ):
        raise ValueError("Explicit reviewed basis and source are required")
    reviewed_at, cutoff = (
        _timestamp(review["reviewed_at"]),
        _timestamp(review["retrieved_before"]),
    )
    if reviewed_at < end or cutoff < end or reviewed_at < cutoff:
        raise ValueError(
            "Basis review and retrieval cutoff must cover the valuation period"
        )
    history = _keys(
        basis["history"], {"status", "from", "through", "missing_periods"}, "history"
    )
    if (
        history["status"] != "complete"
        or history["missing_periods"] != []
        or _timestamp(history["from"]) != start
        or _timestamp(history["through"]) != end
    ):
        raise ValueError(
            "Explicit complete history must cover exactly the performance period"
        )
    currency = performance.base_currency
    positions: list[dict[tuple[str, str], tuple[Decimal, Decimal]]] = []
    for name in ("opening_positions", "closing_positions"):
        if not isinstance(basis[name], list):
            raise ValueError(f"{name} must be an array")
        parsed = {}
        for row in basis[name]:
            _keys(
                row,
                {
                    "account_id",
                    "holding_id",
                    "currency",
                    "quantity",
                    "market_value_native",
                },
                name,
            )
            key = _identity(row, currency)
            if key in parsed:
                raise ValueError(f"Duplicate {name} identity")
            qty, value = _number(row["quantity"]), _number(row["market_value_native"])
            if qty == 0 and value != 0:
                raise ValueError("Zero quantity cannot carry nonzero market value")
            parsed[key] = (qty, value)
        positions.append(parsed)
    opening, closing = positions
    opening_cash, closing_cash = (
        _number(basis["opening_cash_base"]),
        _number(basis["closing_cash_base"]),
    )
    for position, cash, expected in [
        (opening, opening_cash, bridge["opening_value_base"]),
        (closing, closing_cash, bridge["closing_value_base"]),
    ]:
        if (
            abs(
                sum((value for _, value in position.values()), cash)
                - Decimal(str(expected))
            )
            > _TOLERANCE
        ):
            raise ValueError(
                "Reviewed cash plus positions does not reconcile with performance bookend"
            )
    if not isinstance(basis["opening_lots"], list):
        raise ValueError("opening_lots must be an array")
    lots: dict[tuple[str, str], list[dict]] = {}
    lot_ids: set[str] = set()
    acquisition_times: set[tuple[tuple[str, str], datetime]] = set()
    for row in basis["opening_lots"]:
        _keys(
            row,
            {
                "id",
                "account_id",
                "holding_id",
                "currency",
                "acquired_at",
                "quantity",
                "total_cost_native",
            },
            "opening lot",
        )
        key = _identity(row, currency)
        aid = row["id"]
        if not isinstance(aid, str) or not aid.strip() or aid in lot_ids:
            raise ValueError("Opening lot IDs must be unique nonempty strings")
        acquired = _timestamp(row["acquired_at"])
        qty, cost = _number(row["quantity"]), _number(row["total_cost_native"])
        if acquired > start or qty <= 0 or (key, acquired) in acquisition_times:
            raise ValueError(
                "Opening lots need positive quantities and unambiguous historical FIFO dates"
            )
        acquisition_times.add((key, acquired))
        lot_ids.add(aid)
        lots.setdefault(key, []).append(
            {"id": aid, "when": acquired, "quantity": qty, "cost": cost}
        )
    for key in set(opening) | set(lots):
        if (
            sum((lot["quantity"] for lot in lots.get(key, [])), Decimal(0))
            != opening.get(key, (Decimal(0), Decimal(0)))[0]
        ):
            raise ValueError(
                "Opening lot quantities do not reconcile with opening positions"
            )
    for rows in lots.values():
        rows.sort(key=lambda lot: lot["when"])
    opening_costs = {
        key: sum((lot["cost"] for lot in rows), Decimal(0))
        for key, rows in lots.items()
    }
    realized: dict[tuple[str, str], Decimal] = {}
    net_income = fees_total = taxes_total = cash_delta = Decimal(0)
    activity_evidence = []
    chronological = []
    for activity in ledger:
        when = _timestamp(activity.get("effective_at"))
        if start <= when <= end:
            if when == start:
                raise ValueError(
                    "Events at opening bookend have ambiguous inclusion; decomposition unavailable"
                )
            chronological.append((when, activity))
    trade_times: set[tuple[tuple[str, str], datetime]] = set()
    for when, activity in sorted(
        chronological, key=lambda item: (item[0], item[1]["id"])
    ):
        event = str(activity.get("event_type", "")).strip().lower()
        if (
            "corporate_action" in activity
            or event not in {"buy", "sell", "fee", "tax_withheld"} | _INCOME | _EXTERNAL
        ):
            raise ValueError(f"Unsupported movement/corporate action {event!r}")
        if (
            event not in ("buy", "sell")
            and "quantity" in activity
            and _number(activity["quantity"], signed=True) != 0
        ):
            raise ValueError("Non-trade quantity movements are unsupported for FIFO")
        money = _keys(activity.get("money"), {"amount", "currency"}, "activity money")
        amount = _number(money["amount"], signed=event in _EXTERNAL)
        if money["currency"] != currency:
            raise ValueError(
                "FIFO supports reporting-currency transactions only; historical FX cost attribution unavailable"
            )
        charges = []
        for field in ("fees", "withholding_tax"):
            charge = activity.get(field, {"amount": 0, "currency": currency})
            _keys(charge, {"amount", "currency"}, field)
            if charge["currency"] != currency:
                raise ValueError(
                    "Cross-currency fees/taxes require unsupported historical cost attribution"
                )
            charges.append(_number(charge["amount"]))
        fees, taxes = charges
        row = {
            "activity_id": activity["id"],
            "event_type": event,
            "effective_at": activity["effective_at"],
            "native_currency": currency,
            "reported_amount_native": _json(amount),
            "reported_fees_native": _json(fees) if "fees" in activity else None,
            "reported_taxes_native": _json(taxes)
            if "withholding_tax" in activity
            else None,
            "applied_fees_native": _json(fees),
            "applied_taxes_native": _json(taxes),
            "provenance": "computed_from_reported_ledger",
        }
        if event in ("buy", "sell"):
            key = _identity({**activity, "currency": currency}, currency)
            qty = _number(activity.get("quantity"))
            if qty <= 0 or (key, when) in trade_times:
                raise ValueError(
                    "Trades need positive quantity and unambiguous FIFO timestamps"
                )
            trade_times.add((key, when))
            rows = lots.setdefault(key, [])
            if event == "buy":
                if activity["id"] in lot_ids:
                    raise ValueError("Buy identity collides with an opening lot")
                lot_ids.add(activity["id"])
                cost = amount + fees + taxes
                rows.append(
                    {"id": activity["id"], "when": when, "quantity": qty, "cost": cost}
                )
                cash = -cost
                row["capitalized_cost_native"] = _json(cost)
            else:
                remainder, cost = qty, Decimal(0)
                consumed = []
                for lot in rows:
                    take = min(remainder, lot["quantity"])
                    if take == 0:
                        continue
                    removed = lot["cost"] * take / lot["quantity"]
                    consumed.append(
                        {
                            "lot_id": lot["id"],
                            "quantity": _json(take),
                            "cost_native": _json(removed),
                        }
                    )
                    lot["quantity"] -= take
                    lot["cost"] -= removed
                    remainder -= take
                    cost += removed
                    if remainder == 0:
                        break
                if remainder != 0:
                    raise ValueError(
                        "Sale exceeds reviewed FIFO inventory; acquisition history incomplete"
                    )
                cash = amount - fees - taxes
                gain = cash - cost
                realized[key] = realized.get(key, Decimal(0)) + gain
                row.update(
                    cost_removed_native=_json(cost),
                    realized_gain_native=_json(gain),
                    consumed_lots=consumed,
                )
        elif event in _INCOME:
            income_basis = income_amount_basis(activity)
            if income_basis == "unknown":
                raise ValueError("Income receipt amount basis is unknown")
            cash = amount if income_basis == "net" else amount - fees - taxes
            net_income += cash
            row["income_amount_basis"] = income_basis
        elif event == "fee":
            cash = -(amount + fees + taxes)
            fees_total += amount + fees
            taxes_total += taxes
        elif event == "tax_withheld":
            cash = -(amount + fees + taxes)
            fees_total += fees
            taxes_total += amount + taxes
        else:
            if fees or taxes or activity.get("quantity") or activity.get("holding_id"):
                raise ValueError(
                    "External flows with costs or in-kind asset references are unsupported for FIFO"
                )
            cash = abs(amount) * (-1 if event == "withdrawal" else 1)
        cash_delta += cash
        row["net_cash_native"] = _json(cash)
        activity_evidence.append(row)
    if abs(opening_cash + cash_delta - closing_cash) > _TOLERANCE:
        raise ValueError(
            "Effective ledger cash movements do not reconcile with reviewed closing cash"
        )
    holding_evidence = []
    opening_unrealized = closing_unrealized = Decimal(0)
    for key in sorted(set(lots) | set(opening) | set(closing)):
        rows = lots.get(key, [])
        quantity = sum((lot["quantity"] for lot in rows), Decimal(0))
        closing_qty, closing_value = closing.get(key, (Decimal(0), Decimal(0)))
        if quantity != closing_qty:
            raise ValueError(
                "Closing quantity differs from reconstructed FIFO inventory"
            )
        opening_cost = opening_costs.get(key, Decimal(0))
        remaining_cost = sum((lot["cost"] for lot in rows), Decimal(0))
        opening_gain = opening.get(key, (Decimal(0), Decimal(0)))[1] - opening_cost
        closing_gain = closing_value - remaining_cost
        opening_unrealized += opening_gain
        closing_unrealized += closing_gain
        holding_evidence.append(
            {
                "account_id": key[0],
                "holding_id": key[1],
                "native_currency": currency,
                "realized_gain_native": _json(realized.get(key, Decimal(0))),
                "opening_unrealized_gain_native": _json(opening_gain),
                "closing_unrealized_gain_native": _json(closing_gain),
                "closing_quantity": _json(quantity),
                "remaining_cost_native": _json(remaining_cost),
            }
        )
    realized_total = sum(realized.values(), Decimal(0))
    change = closing_unrealized - opening_unrealized
    explained = realized_total + change + net_income - fees_total - taxes_total
    difference = Decimal(str(bridge["investment_result_base"])) - explained
    if abs(difference) > _TOLERANCE:
        raise ValueError(
            "FIFO components do not reconcile with period investment result"
        )
    values = (
        realized_total,
        opening_unrealized,
        closing_unrealized,
        change,
        net_income,
        fees_total,
        taxes_total,
        explained,
        difference,
    )
    return {
        "status": "complete",
        "method": "fifo",
        **{key: _json(value) for key, value in zip(_COMPONENTS, values)},
        "holdings": holding_evidence,
        "activity_evidence": activity_evidence,
        "basis_evidence": copy.deepcopy(basis),
    }


def compute_profit_attribution(
    portfolio: dict,
    performance: PerformanceResult,
    *,
    basis: dict | None = None,
    historical_fx: HistoricalFx | None = None,
) -> dict:
    """Expose a complete bridge where possible, and optional verified FIFO evidence.

    Top-level status describes the bridge only (``status_scope='bridge'``).
    Decomposition has its own availability. Invalid evidence yields diagnostics
    and null component totals, never a partial sum disguised as complete profit.
    """
    bridge = {
        "status": "unavailable",
        "opening_value_base": None,
        "net_external_cashflow_base": None,
        "investment_result_base": None,
        "closing_value_base": None,
        "equation": "opening + net_external_flows + investment_result = closing",
        "provenance": "computed_from_performance_bookends_and_effective_ledger",
        "cashflow_evidence": [],
    }
    decomposition = {
        "status": "unavailable",
        "method": "fifo",
        **{key: None for key in _COMPONENTS},
        "holdings": [],
        "activity_evidence": [],
        "basis_evidence": None,
    }
    result = {
        "contract_version": "1.0",
        "scope": "portfolio",
        "return_basis": "period",
        "status": "unavailable",
        "status_scope": "bridge",
        "base_currency": performance.base_currency,
        "period_start": performance.period_start,
        "period_end": performance.period_end,
        "bridge": bridge,
        "decomposition": decomposition,
        "diagnostics": [],
        "treatment": {
            "investment_result": "residual already includes income, fees and taxes present in NAV; never add income again",
            "realized_gain": "period sales less historical FIFO costs and sale charges",
            "unrealized_change": "closing unrealized gain minus opening unrealized gain; not lifetime profit",
            "native_and_base": "FIFO supports identical native/reporting currency only; FX decomposition unavailable",
            "reported_profit": "not used; all result totals are computed",
        },
    }
    try:
        ledger = _effective_ledger(portfolio)
        result["bridge"] = _bridge(portfolio, performance, ledger, historical_fx)
        result["status"] = "complete"
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        result["diagnostics"].append(f"Bridge unavailable: {exc}")
        return result
    if basis is None:
        result["diagnostics"].append(
            "FIFO decomposition unavailable: explicit reviewed basis/history evidence is required"
        )
        return result
    try:
        result["decomposition"] = _fifo_decomposition(
            basis, ledger, performance, result["bridge"]
        )
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        result["diagnostics"].append(f"FIFO decomposition unavailable: {exc}")
    return result
