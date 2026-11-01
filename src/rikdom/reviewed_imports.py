"""Durable source observations and reviewed overlays for recurring imports.

prepare_reviewed_import borrows both inputs read-only and returns an effective
statement, preview and pending state. Persist that state only after all normal
merge/financial checks pass. Revisions retain exact normalized source and effective
portfolio inputs, without recursively embedding earlier revisions.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any
from importlib.resources import files as resource_files

from .import_preflight import import_diagnostics

_KEY = "rikdom_reviewed_imports"
_COLLECTIONS = ("holdings", "activities", "tax_lots", "statement_observations")
_PROTECTED = {"id", "idempotency_key", "source_system", "import_run_id", "ingested_at", "created_at", "source_ref", "provenance", "extensions"}


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in ("import_run_id", "ingested_at")}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(_stable(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _overlay(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in changes.items():
        result[key] = _overlay(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else copy.deepcopy(value)
    return result


def _contradictions(before: Any, incoming: Any, path: str = "") -> list[str]:
    # Omitted optional evidence is not an assertion retracting previous evidence.
    if isinstance(before, dict) and isinstance(incoming, dict):
        return [field for key in sorted(before.keys() & incoming.keys()) for field in _contradictions(before[key], incoming[key], f"{path}.{key}" if path else key)]
    return [path] if before != incoming else []



def _new_assertions(source: dict[str, Any], incoming: dict[str, Any], patch: dict[str, Any], path: str = "") -> list[str]:
    changed = []
    for key, value in patch.items():
        if key not in incoming:
            continue
        field = f"{path}.{key}" if path else key
        if isinstance(value, dict) and isinstance(incoming[key], dict):
            changed.extend(_new_assertions(source.get(key) if isinstance(source.get(key), dict) else {}, incoming[key], value, field))
        elif key not in source and value != incoming[key]:
            changed.append(field)
    return changed


def _validate_effective_review(collection: str, target: dict[str, Any]) -> None:
    if collection == "diagnostics":
        from .import_preflight import validate_import_diagnostics
        errors = validate_import_diagnostics(target)
    else:
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads(resource_files("rikdom._resources").joinpath("portfolio.schema.json").read_text(encoding="utf-8"))
        name = {"holdings": "Holding", "activities": "Activity", "tax_lots": "TaxLot", "statement_observations": "StatementObservation"}[collection]
        value = copy.deepcopy(target)
        if collection == "activities":
            value.setdefault("status", "posted")
        validator = Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}, format_checker=FormatChecker())
        errors = [f"{'.'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(value)]
    if errors:
        raise ValueError(f"Invalid effective review {collection}: {'; '.join(errors)}")

def _snapshot(portfolio: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(portfolio)
    if isinstance(result.get("extensions"), dict):
        result["extensions"].pop(_KEY, None)
        if not result["extensions"]:
            result.pop("extensions")
    return result


def _check_identities(portfolio: dict[str, Any], imported: dict[str, Any]) -> None:
    for collection in _COLLECTIONS:
        incoming = imported.get(collection) or []
        if not isinstance(incoming, list):
            continue  # Existing preflight reports malformed collections.
        rows = [r for r in incoming if isinstance(r, dict)]
        ids: set[str] = set()
        keys: set[str] = set()
        old = [r for r in portfolio.get(collection, []) if isinstance(r, dict)]
        for row in rows:
            rid = row.get("id")
            key = row.get("idempotency_key") if collection == "activities" else (row.get("provenance") or {}).get("idempotency_key")
            if rid in ids or key and key in keys:
                raise ValueError(f"Ambiguous {collection} imported ID/idempotency key")
            if isinstance(rid, str):
                ids.add(rid)
            if isinstance(key, str):
                keys.add(key)
            matches = [r for r in old if r.get("id") == rid or key and (r.get("idempotency_key") if collection == "activities" else (r.get("provenance") or {}).get("idempotency_key")) == key]
            if len(matches) > 1:
                raise ValueError(f"Ambiguous {collection} ID and idempotency key match different stored rows")


def _reject_reviewed_collapses(portfolio: dict[str, Any], imported: dict[str, Any], state: dict[str, Any]) -> None:
    # Reuse the actual matcher and merge sequence, including same-batch changes.
    # A canonical match alone does not authorize migrating a reviewed entity ID.
    from .plugins import _canonical_position_match, merge_holdings

    reviewed_ids = {d["entity_id"] for d in state["decisions"] if d.get("status") == "active" and d.get("collection") == "holdings"}
    if not reviewed_ids:
        return
    candidate = {"holdings": reviewed_merge_base(portfolio, state).get("holdings") or []}
    for row in imported.get("holdings", []) or []:
        if not isinstance(row, dict):
            continue
        holdings = candidate["holdings"]
        if not any(old.get("id") == row.get("id") for old in holdings):
            match = _canonical_position_match(holdings, row)
            if match is not None and (holdings[match].get("id") in reviewed_ids or row.get("id") in reviewed_ids):
                raise ValueError("Canonical collapse changes a reviewed identity; explicit identity migration is required")
        merge_holdings(candidate, {"holdings": [row]}, collapse_canonical=True)


def prepare_reviewed_import(portfolio: dict[str, Any], imported: dict[str, Any], review: dict[str, Any] | None = None, *, collapse_canonical: bool = False) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Apply bound reviews to source input; conflicts require revision-bound resolution.

    Review v1 accepts decisions (id, collection, entity_id, changes, evidence)
    and resolutions (decision_id, source_revision, action, reason). Supported
    actions are keep_review and accept_source. Diagnostics use collection
    diagnostics and entity_id statement. Identity/provenance/correction fields
    cannot be patched; linked corrections remain the ledger's separate contract.
    """
    _check_identities(portfolio, imported)
    existing = (portfolio.get("extensions") or {}).get(_KEY)
    if existing is not None and (not isinstance(existing, dict) or type(existing.get("version")) is not int or existing["version"] != 1):
        raise ValueError("Unsupported reviewed import state version")
    state = copy.deepcopy(existing) if existing is not None else {"version": 1, "decisions": [], "revisions": [], "initial_effective": _snapshot(portfolio)}
    # Earlier v1 imports could save a decision under an incoming alias while
    # canonical collapse stored a different ID. That binding is unverifiable;
    # reject it rather than guessing a migration from account/key similarities.
    stored_holding_ids = {row.get("id") for row in portfolio.get("holdings", []) if isinstance(row, dict)}
    for saved_decision in state["decisions"]:
        if saved_decision.get("status") == "active" and saved_decision.get("collection") == "holdings" and saved_decision["entity_id"] not in stored_holding_ids:
            raise ValueError(f"Stored reviewed identity {saved_decision['entity_id']!r} has no matching holding ID; explicit identity repair is required")
    if review is None:
        review = {"version": 1}
    if not isinstance(review, dict) or type(review.get("version")) is not int or review["version"] != 1:
        raise ValueError("Review document must declare version 1")
    for key in ("decisions", "resolutions"):
        if key in review and not isinstance(review[key], list):
            raise ValueError(f"Review {key} must be an array")
    provider = str(imported.get("provider") or "unknown")
    state["retired_overlays"] = []
    for decision in state["decisions"]:
        if decision.get("status") != "active" or decision.get("collection") == "diagnostics":
            continue
        collection = decision["collection"]
        source = decision.get("accepted_source", decision["source"])
        source_key = source.get("idempotency_key") if collection == "activities" else (source.get("provenance") or {}).get("idempotency_key")
        for row in imported.get(collection, []):
            if not isinstance(row, dict):
                continue
            incoming_key = row.get("idempotency_key") if collection == "activities" else (row.get("provenance") or {}).get("idempotency_key")
            if row.get("id") == decision["entity_id"] and decision.get("provider") != provider:
                raise ValueError("Changed provider collides with a reviewed identity; explicit identity migration is required")
            if source_key and incoming_key == source_key and row.get("id") != decision["entity_id"]:
                raise ValueError("Changed ID bypasses a reviewed identity; explicit identity migration is required")
    revision = _digest(imported)
    provider = str(imported.get("provider") or "unknown")
    effective = copy.deepcopy(imported)
    targets = {(collection, row.get("id")): row for collection in _COLLECTIONS for row in effective.get(collection, []) if isinstance(row, dict)}
    diagnostics = copy.deepcopy(import_diagnostics(effective))
    targets[("diagnostics", "statement")] = diagnostics
    source_targets = copy.deepcopy(targets)
    resolutions: dict[str, dict[str, Any]] = {}
    for resolution in review.get("resolutions", []):
        if not isinstance(resolution, dict) or not isinstance(resolution.get("decision_id"), str) or resolution.get("action") not in ("keep_review", "accept_source") or not isinstance(resolution.get("reason"), str) or not resolution["reason"].strip() or resolution.get("source_revision") != revision:
            raise ValueError("Resolution requires decision_id, keep_review/accept_source, reason and exact preview source_revision")
        if resolution["decision_id"] in resolutions:
            raise ValueError("Duplicate review resolution")
        resolutions[resolution["decision_id"]] = resolution
    conflicts = []
    applied: list[str] = []
    consumed: set[str] = set()
    for decision in state["decisions"]:
        if decision.get("status") != "active" or decision.get("provider") != provider:
            continue
        target_key = (decision["collection"], decision["entity_id"])
        target = targets.get(target_key)
        if target is None:
            continue
        accepted_source = decision.get("accepted_source", decision["source"])
        changed = sorted(set(_contradictions(accepted_source, _stable(target)) + _new_assertions(accepted_source, _stable(target), decision["changes"])))
        resolution = resolutions.get(decision["id"])
        if changed and resolution is None:
            conflicts.append({"decision_id": decision["id"], "decision_version": decision["version"], "collection": decision["collection"], "entity_id": decision["entity_id"], "changed_source_fields": changed, "previous_source": accepted_source, "incoming_source": _stable(target), "reviewed_changes": decision["changes"], "affected_results": ["valuation", "coverage", "reconciliation", "performance", "transfer_identity"], "resolution_required": True})
            continue
        if resolution is not None:
            consumed.add(decision["id"])
            decision.setdefault("history", []).append({k: copy.deepcopy(v) for k, v in decision.items() if k != "history"})
            if resolution["action"] == "accept_source":
                state["retired_overlays"].append(copy.deepcopy(decision))
            decision["version"] += 1
            decision["resolution"] = copy.deepcopy(resolution)
        # Accepted source observations advance independently of the original
        # reviewed baseline. Omission never retracts established source facts.
        observed = _overlay(accepted_source, _stable(source_targets[target_key]))
        if "accepted_source" not in decision or observed != accepted_source:
            decision["accepted_source"] = observed
            decision["accepted_source_revision"] = revision
        effective_source = _overlay(accepted_source, source_targets[target_key])
        source_targets[target_key] = copy.deepcopy(effective_source)
        target.clear()
        if resolution is not None and resolution["action"] == "accept_source":
            decision["status"] = "retired"
            target.update(effective_source)
            continue
        target.update(_overlay(effective_source, decision["changes"]))
        _validate_effective_review(decision["collection"], target)
        applied.append(decision["id"])
    if set(resolutions) != consumed:
        raise ValueError("Resolution references an inactive, unknown or absent decision")
    seen: set[str] = set()
    for entry in review.get("decisions", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip() or entry["id"] in seen:
            raise ValueError("Review decisions require unique nonempty IDs")
        seen.add(entry["id"])
        previous = next((d for d in state["decisions"] if d["id"] == entry["id"]), None)
        if previous is not None:
            if previous.get("status") == "active" and previous.get("provider") == provider and all(previous.get(k) == entry.get(k) for k in ("collection", "entity_id", "changes", "evidence")):
                continue
            raise ValueError("Existing decisions require an explicit resolution; use a new ID for a new review")
        key = (entry.get("collection"), entry.get("entity_id"))
        if key not in targets:
            raise ValueError("Review decision references an unknown imported entity")
        changes = entry.get("changes")
        if not isinstance(changes, dict) or not changes or _PROTECTED.intersection(changes):
            raise ValueError("Review changes must be a nonempty patch without identity/provenance/correction fields")
        metadata = changes.get("metadata")
        if "metadata" in changes and not isinstance(metadata, dict):
            raise ValueError("Review metadata must be an object preserving source identity")
        if isinstance(metadata, dict) and {"rikdom_source_identity", "canonical_key", "collapsed_from"}.intersection(metadata):
            raise ValueError("Review changes cannot replace source/canonical identity metadata")
        evidence = entry.get("evidence")
        if not isinstance(evidence, dict) or evidence.get("kind") not in ("source", "user_declaration") or not isinstance(evidence.get("source_ref"), str) or not evidence["source_ref"].strip():
            raise ValueError("Review decision needs explicit evidence kind and source_ref")
        if any(d.get("status") == "active" and d.get("provider") == provider and (d["collection"], d["entity_id"]) == key for d in state["decisions"]):
            raise ValueError("Resolve or retire the active review before adding another for this entity")
        decision = {**copy.deepcopy(entry), "provider": provider, "version": 1, "status": "active", "source_revision": revision, "source": _stable(source_targets[key]), "accepted_source_revision": revision, "accepted_source": _stable(source_targets[key])}
        state["decisions"].append(decision)
        target = targets[key]
        enriched = _overlay(target, changes)
        target.clear()
        target.update(enriched)
        _validate_effective_review(entry["collection"], target)
        applied.append(entry["id"])
    if ("diagnostics", "statement") in targets and any(d.get("collection") == "diagnostics" and d.get("provider") == provider for d in state["decisions"]):
        effective.setdefault("metadata", {})["rikdom_import_diagnostics"] = diagnostics
    if collapse_canonical:
        _reject_reviewed_collapses(portfolio, effective, state)
    return effective, {"version": 1, "ok": not conflicts, "source_revision": revision, "applied_decision_ids": applied, "conflicts": conflicts}, state


def retain_reviewed_import(portfolio: dict[str, Any], source: dict[str, Any], state: dict[str, Any]) -> None:
    """Commit pending review state only on the validated candidate portfolio."""
    state = copy.deepcopy(state)
    state.pop("retired_overlays", None)
    effective = _snapshot(portfolio)
    reviews = copy.deepcopy(state["decisions"])
    content_hash = _digest({"source": source, "effective": effective, "reviews": reviews})
    if not state["revisions"] or state["revisions"][-1]["content_hash"] != content_hash:
        state["revisions"].append({"version": len(state["revisions"]) + 1, "content_hash": content_hash, "source_revision": _digest(source), "source": copy.deepcopy(source), "reviews": reviews, "effective": effective})
    portfolio.setdefault("extensions", {})[_KEY] = copy.deepcopy(state)


def reviewed_merge_base(portfolio: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Detach the candidate and restore leaves of explicitly retired overlays.

    Normal recursive holding merges retain omitted fields. Retiring an overlay
    therefore restores its source leaves before the usual merge runs, preserving
    unrelated enrichments and avoiding stale review-only values.
    """
    result = copy.deepcopy(portfolio)

    def restore(target: dict[str, Any], source: dict[str, Any], patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                original = source.get(key) if isinstance(source.get(key), dict) else {}
                restore(target[key], original, value)
                if not target[key] and key not in source:
                    target.pop(key)
            elif key in source:
                target[key] = copy.deepcopy(source[key])
            else:
                target.pop(key, None)

    for decision in state.get("retired_overlays", []):
        if decision["collection"] == "diagnostics":
            continue  # Diagnostics replace their whole statement on merge.
        row = next((r for r in result.get(decision["collection"], []) if r.get("id") == decision["entity_id"]), None)
        if row is not None:
            restore(row, decision.get("accepted_source", decision["source"]), decision["changes"])
    return result
