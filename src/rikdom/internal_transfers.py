"""Resolve reviewed v1 cash-pair identities over the effective ledger.

Only explicit metadata can establish a pair. Identity, deduplication, correction
projection and cash-only eligibility live here so portfolio returns and profit
bridges suppress exactly the same legs. Scoped returns keep the projected legs.
This verifies a supplied claim, not the completeness of the transaction history.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import math
from typing import Any

from .activities import effective_activities

_KEY = "rikdom_internal_transfer"


def _instant(raw: Any) -> datetime:
    if not isinstance(raw, str) or "T" not in raw:
        raise ValueError("an explicit timezone timestamp is required")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("an explicit timezone timestamp is required")
    return parsed.astimezone(timezone.utc)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _amount(value: Any) -> Decimal:
    if type(value) not in (int, float):
        raise ValueError("cash amounts must be finite numbers")
    try:
        if not math.isfinite(value):
            raise ValueError("cash amounts must be finite numbers")
    except OverflowError:
        raise ValueError("cash amounts must be finite numbers") from None
    return Decimal(str(value))


def _posted(row: dict) -> bool:
    value = row.get("status", "posted")
    return (
        value is None
        or isinstance(value, str)
        and value.strip().lower() in ("", "posted")
    )


@dataclass(frozen=True)
class InternalTransfers:
    activities: list[dict[str, Any]]
    internal_activity_ids: frozenset[str]
    provenance: dict[str, Any]
    warnings: list[str]

    @property
    def external_activities(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.activities
            if not isinstance(row.get("id"), str)
            or row["id"] not in self.internal_activity_ids
        ]


def resolve_internal_transfers(
    activities: list[dict[str, Any]],
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> InternalTransfers:
    """Validate complete identities before filtering evidence to an inclusive window.

    Exact replays collapse by ID or idempotency key; conflicting identities never
    establish a pair. Invalid in-window claims disable exact portfolio returns.
    A malformed timestamp is relevant because its exclusion cannot be proven.
    Inputs are borrowed read-only; published provenance is fully detached.
    """
    effective = effective_activities(activities)
    has_claim = any(
        isinstance(row.get("metadata"), dict) and _KEY in row["metadata"]
        for row in effective
    )
    rows: list[dict[str, Any]] = []
    ids: dict[str, dict] = {}
    imports: dict[str, dict] = {}
    conflicts: set[str] = set()
    replay_ids: dict[str, set[str]] = {}
    collapsed_replays: list[dict[str, Any]] = []
    for row in effective:
        if not has_claim:
            rows.append(row)
            continue
        aid = row.get("id")
        if _text(aid):
            if aid in ids:
                if {
                    k: v
                    for k, v in row.items()
                    if k not in ("import_run_id", "ingested_at")
                } == {
                    k: v
                    for k, v in ids[aid].items()
                    if k not in ("import_run_id", "ingested_at")
                }:
                    continue
                conflicts.add(aid)
            else:
                ids[aid] = row
        key = row.get("idempotency_key")
        if _text(key):
            content = {
                k: v
                for k, v in row.items()
                if k not in ("id", "import_run_id", "ingested_at", "provenance")
            }
            if key in imports:
                previous = imports[key]
                previous_id = previous.get("id")
                if _text(aid) and _text(previous_id):
                    replay_ids.setdefault(aid, set()).add(previous_id)
                    replay_ids.setdefault(previous_id, set()).add(aid)
                previous_content = {
                    k: v
                    for k, v in previous.items()
                    if k not in ("id", "import_run_id", "ingested_at", "provenance")
                }
                if content == previous_content and _text(aid) and _text(previous_id):
                    collapsed_replays.append(row)
                    continue
                conflicts.update(v for v in (aid, previous.get("id")) if _text(v))
            else:
                imports[key] = row
        rows.append(row)

    # A replay may disappear from the projection, but its identity remains
    # connected to the canonical leg if another row later conflicts with it.
    pending = list(conflicts)
    while pending:
        for related in replay_ids.get(pending.pop(), ()):
            if related not in conflicts:
                conflicts.add(related)
                pending.append(related)
    # Keep the witness rows of a conflicting identity component. Re-resolving
    # this projection must not erase the conflict after a replay was collapsed.
    rows.extend(row for row in collapsed_replays if row.get("id") in conflicts)

    def relevant(legs: list[dict]) -> bool:
        for leg in legs:
            try:
                when = _instant(leg.get("effective_at"))
            except (ValueError, TypeError):
                return True
            if (period_start is None or when >= period_start) and (
                period_end is None or when <= period_end
            ):
                return True
        return False

    groups: dict[str, list[dict]] = {}
    issues: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    internal_ids: set[str] = set()

    def issue(legs: list[dict], reason: str, pair_id: str | None = None) -> None:
        if relevant(legs):
            issues.append(
                {
                    "pair_id": pair_id,
                    "activity_ids": [
                        row.get("id") if _text(row.get("id")) else None for row in legs
                    ],
                    "reason": reason,
                }
            )

    for row in rows:
        metadata = row.get("metadata")
        if not isinstance(metadata, dict) or _KEY not in metadata:
            continue
        claim = metadata[_KEY]
        if not isinstance(claim, dict) or not _text(claim.get("pair_id")):
            if _posted(row):
                issue(
                    [row],
                    "A versioned internal-transfer claim requires a nonempty pair_id",
                )
            continue
        groups.setdefault(claim["pair_id"], []).append(row)
    for pair_id, claimed in sorted(groups.items()):
        legs = [row for row in claimed if _posted(row)]
        if not legs:
            continue
        try:
            if len(legs) != 2:
                raise ValueError("Exactly two effective posted cash legs are required")
            claims = [row["metadata"][_KEY] for row in legs]
            for claim in claims:
                if (
                    set(claim) != {"version", "pair_id", "review"}
                    or type(claim.get("version")) is not int
                    or claim["version"] != 1
                ):
                    raise ValueError(
                        "Supported internal-transfer metadata requires version 1, pair_id and review"
                    )
                review = claim.get("review")
                if (
                    not isinstance(review, dict)
                    or set(review) != {"status", "source", "reviewed_at"}
                    or review.get("status") != "reviewed"
                    or not _text(review.get("source"))
                ):
                    raise ValueError(
                        "Explicit reviewed source and reviewed_at are required"
                    )
                _instant(review.get("reviewed_at"))
            if claims[0] != claims[1]:
                raise ValueError(
                    "Both cash legs must carry identical reviewed pair metadata"
                )
            aids = [row.get("id") for row in legs]
            if (
                not all(_text(aid) for aid in aids)
                or len(set(aids)) != 2
                or any(aid in conflicts for aid in aids)
            ):
                raise ValueError(
                    "Cash legs require unique stable activity IDs without conflicting replays"
                )
            accounts = [row.get("account_id") for row in legs]
            if (
                not all(_text(account) for account in accounts)
                or accounts[0].strip() == accounts[1].strip()
            ):
                raise ValueError("Cash legs require distinct explicit account IDs")
            if {str(row.get("event_type", "")).strip().lower() for row in legs} != {
                "transfer_in",
                "transfer_out",
            }:
                raise ValueError("One transfer_in and one transfer_out are required")
            instants = [_instant(row.get("effective_at")) for row in legs]
            if instants[0] != instants[1]:
                raise ValueError("Asynchronous cash transfers are unsupported")
            amounts, currencies = [], []
            for row in legs:
                money = row.get("money")
                if not isinstance(money, dict) or set(money) != {"amount", "currency"}:
                    raise ValueError("Cash legs require explicit amount and currency")
                amount, currency = _amount(money["amount"]), money["currency"]
                if (
                    amount <= 0
                    or not isinstance(currency, str)
                    or len(currency) != 3
                    or not currency.isascii()
                    or not currency.isalpha()
                    or not currency.isupper()
                ):
                    raise ValueError(
                        "Cash legs require positive amounts and uppercase currency codes"
                    )
                amounts.append(amount)
                currencies.append(currency)
                if (
                    row.get("holding_id") is not None
                    or bool(row.get("tax_lot_ids"))
                    or "corporate_action" in row
                    or "cost_basis_adjustment" in row
                    or ("quantity" in row and _amount(row["quantity"]) != 0)
                ):
                    raise ValueError(
                        "In-kind transfers and asset/basis movements are unsupported"
                    )
                for field in ("fees", "withholding_tax"):
                    if field in row:
                        charge = row[field]
                        if (
                            not isinstance(charge, dict)
                            or set(charge) != {"amount", "currency"}
                            or charge["currency"] != currency
                            or _amount(charge["amount"]) != 0
                        ):
                            raise ValueError(
                                "Transfer costs require separate ledger events"
                            )
            if amounts[0] != amounts[1] or currencies[0] != currencies[1]:
                raise ValueError(
                    "Cash legs require identical native amounts and currencies; cross-currency pairs are unsupported"
                )
            internal_ids.update(aids)
            if relevant(legs):
                ordered = sorted(
                    legs,
                    key=lambda row: str(row["event_type"]).strip().lower()
                    == "transfer_in",
                )
                pairs.append(
                    {
                        "pair_id": pair_id,
                        "activity_ids": [row["id"] for row in ordered],
                        "account_ids": [row["account_id"] for row in ordered],
                        "effective_at": instants[0].isoformat(),
                        "amount_native": legs[0]["money"]["amount"],
                        "currency": currencies[0],
                        "review": copy.deepcopy(claims[0]["review"]),
                    }
                )
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            issue(legs, str(exc), pair_id)
    warnings = [
        "Invalid financial input: internal-transfer claim: " + row["reason"]
        for row in issues
    ]
    return InternalTransfers(
        rows,
        frozenset(internal_ids),
        {
            "version": 1,
            "status": "unavailable" if issues else "verified" if pairs else "none",
            "pairs": pairs,
            "issues": issues,
        },
        warnings,
    )
