"""Correction integrity and the effective projection of an immutable activity ledger.

Stored events are never rewritten by a correction. Calculation projections omit
superseded events and correction links, so composing calculations is idempotent.
"""
from __future__ import annotations

import copy
from typing import Any


CORRECTION_SCHEMA_VERSION = "2.0.0"
_RUN_FIELDS = {"import_run_id", "ingested_at"}


def correction(activity: dict[str, Any]) -> dict[str, Any] | None:
    ext = activity.get("extensions") or {}
    if not isinstance(ext, dict) or "rikdom_correction" not in ext:
        return None
    value = ext["rikdom_correction"]
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("Unsupported correction version; expected version 1")
    if not isinstance(value.get("supersedes_activity_id"), str) or not value["supersedes_activity_id"].strip() or not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise ValueError("Correction needs supersedes_activity_id and reason")
    if activity.get("status", "posted") not in ("posted", "cancelled"):
        raise ValueError("A correction must be posted or cancelled")
    return value


def effective_activities(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [a for a in activities if isinstance(a, dict)]
    corrections = [(a, correction(a)) for a in rows]
    if not any(c for _, c in corrections):
        return rows
    by_id = {a.get("id"): a for a in rows}
    if len(by_id) != len(rows) or any(not a.get("id") for a in rows):
        raise ValueError("Correction ledger requires unique activity IDs")
    targets: dict[str, str] = {}
    parents: dict[str, str] = {}
    for a, c in corrections:
        if c is None:
            continue
        target = c["supersedes_activity_id"]
        if target not in by_id:
            raise ValueError(f"Correction target {target!r} does not exist")
        if target in targets:
            raise ValueError(f"Correction fork at {target!r}")
        targets[target] = a["id"]
        parents[a["id"]] = target
    for aid in parents:
        seen: set[str] = set()
        cursor = aid
        while cursor in parents:
            if cursor in seen:
                raise ValueError("Correction cycle")
            seen.add(cursor)
            cursor = parents[cursor]
    selected = []
    for activity in rows:
        if activity["id"] in targets:
            continue
        value = copy.deepcopy(activity)
        if isinstance(value.get("extensions"), dict):
            value["extensions"].pop("rikdom_correction", None)
        selected.append(value)
    return selected


def check_financial_contract(portfolio: dict[str, Any]) -> None:
    from .validate import _check_schema_compatibility

    version = portfolio.get("schema_version")
    errors: list[str] = []
    _check_schema_compatibility(portfolio, errors)
    if errors:
        raise ValueError("; ".join(errors))
    activities = portfolio.get("activities") or []
    has_corrections = any(correction(a) is not None for a in activities if isinstance(a, dict))
    if has_corrections and version != CORRECTION_SCHEMA_VERSION:
        raise ValueError("Correction-bearing portfolios require schema_version 2.0.0")
    if has_corrections:
        effective_activities(activities)


def _stable(activity: dict[str, Any]) -> dict[str, Any]:
    value = {k: v for k, v in activity.items() if k not in _RUN_FIELDS}
    value.setdefault("status", "posted")
    return value


def validate_activity_import(portfolio: dict[str, Any], imported: dict[str, Any]) -> None:
    """Reject a destructive correction before the ordinary id/key merge runs."""
    old = [a for a in portfolio.get("activities", []) if isinstance(a, dict)]
    incoming = [a for a in imported.get("activities", []) if isinstance(a, dict)]
    by_id = {a.get("id"): a for a in old}
    by_key = {a.get("idempotency_key"): a for a in old if a.get("idempotency_key")}
    protected = set()
    for a in [*old, *incoming]:
        c = correction(a)
        if c:
            protected.update((a["id"], c["supersedes_activity_id"]))
    new_corrections = [a for a in incoming if correction(a) and a.get("id") not in by_id]
    if len(new_corrections) > 1:
        raise ValueError("Apply one new correction at a time")
    candidate = list(old)
    for activity in incoming:
        c = correction(activity)
        previous = by_id.get(activity.get("id"))
        key_previous = by_key.get(activity.get("idempotency_key"))
        if previous and _stable(previous) == _stable(activity):
            continue
        if previous and (c or previous.get("id") in protected):
            raise ValueError("Conflicting correction identity/content would overwrite an immutable activity")
        if key_previous and (c or key_previous.get("id") in protected):
            raise ValueError("Correction idempotency key collides with an existing activity")
        if c:
            if not activity.get("idempotency_key"):
                raise ValueError("Correction requires its own idempotency key")
            target = next((a for a in old if a.get("id") == c["supersedes_activity_id"]), None)
            if target is None:
                raise ValueError("Correction target does not exist")
            if any(correction(a) and correction(a)["supersedes_activity_id"] == target["id"] for a in candidate):
                raise ValueError("Correction target is no longer current")
            lots = [lot.get("id") for lot in [*(portfolio.get("tax_lots") or []), *(imported.get("tax_lots") or [])] if isinstance(lot, dict) and (lot.get("acquisition_activity_id") == target["id"] or lot.get("disposal_activity_id") == target["id"])]
            if lots or target.get("tax_lot_ids") or target.get("corporate_action") or activity.get("tax_lot_ids") or activity.get("corporate_action"):
                raise ValueError(f"Correction requires review of dependent tax lots/corporate action: {lots or target['id']}")
        if previous:
            candidate = [activity if a.get("id") == previous["id"] else a for a in candidate]
        else:
            candidate.append(activity)
        by_id[activity.get("id")] = activity
        if activity.get("idempotency_key"):
            by_key[activity["idempotency_key"]] = activity
    effective_activities(candidate)
    superseded = {c["supersedes_activity_id"] for a in candidate if (c := correction(a))}
    for lot in imported.get("tax_lots") or []:
        if isinstance(lot, dict) and (lot.get("acquisition_activity_id") in superseded or lot.get("disposal_activity_id") in superseded):
            raise ValueError(f"Incoming tax lot {lot.get('id')} references a superseded activity")
