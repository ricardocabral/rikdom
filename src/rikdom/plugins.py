from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


_RUN_SCOPED_FIELDS = ("import_run_id", "ingested_at")


@dataclass(slots=True)
class MergeCounts:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def _canonical_content(entry: dict[str, Any], exclude: tuple[str, ...]) -> str:
    filtered = {k: v for k, v in entry.items() if k not in exclude}
    return json.dumps(filtered, sort_keys=True, ensure_ascii=False)


def _holding_provenance(entry: dict[str, Any]) -> dict[str, Any]:
    prov = entry.get("provenance")
    return prov if isinstance(prov, dict) else {}


def _holding_content_hash(entry: dict[str, Any]) -> str:
    shallow = dict(entry)
    prov = _holding_provenance(entry)
    stable_prov = {k: v for k, v in prov.items() if k not in _RUN_SCOPED_FIELDS}
    if stable_prov:
        shallow["provenance"] = stable_prov
    else:
        shallow.pop("provenance", None)
    return json.dumps(shallow, sort_keys=True, ensure_ascii=False)


def _activity_content_hash(entry: dict[str, Any]) -> str:
    return _canonical_content(entry, exclude=_RUN_SCOPED_FIELDS)


def _idempotency_key_for_holding(entry: dict[str, Any], source_system: str) -> str:
    prov = _holding_provenance(entry)
    if prov.get("idempotency_key"):
        return str(prov["idempotency_key"])
    hid = str(entry.get("id", "")).strip()
    seed = f"{source_system}|holding|{hid}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _idempotency_key_for_activity(entry: dict[str, Any], source_system: str) -> str:
    if entry.get("idempotency_key"):
        return str(entry["idempotency_key"])
    aid = str(entry.get("id", "")).strip()
    effective = str(entry.get("effective_at", "")).strip()
    seed = f"{source_system}|activity|{aid}|{effective}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def stamp_provenance(
    imported: dict[str, Any],
    *,
    source_system: str,
    import_run_id: str,
    ingested_at: str,
) -> dict[str, Any]:
    """Stamp run-scoped provenance onto every holding/activity in place and return the payload."""
    for entry in imported.get("holdings", []) or []:
        if not isinstance(entry, dict):
            continue
        prov = dict(_holding_provenance(entry))
        prov.setdefault("source_system", source_system)
        prov.setdefault("idempotency_key", _idempotency_key_for_holding(entry, source_system))
        prov["import_run_id"] = import_run_id
        prov["ingested_at"] = ingested_at
        entry["provenance"] = prov

    for entry in imported.get("activities", []) or []:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("source_system", source_system)
        entry.setdefault("idempotency_key", _idempotency_key_for_activity(entry, source_system))
        entry["import_run_id"] = import_run_id
        entry["ingested_at"] = ingested_at

    return imported


def merge_holdings(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> tuple[dict[str, Any], MergeCounts]:
    holdings = portfolio.get("holdings")
    if not isinstance(holdings, list):
        holdings = []
        portfolio["holdings"] = holdings

    current_index: dict[str, int] = {}
    for i, item in enumerate(holdings):
        if isinstance(item, dict) and item.get("id"):
            current_index[str(item["id"])] = i

    counts = MergeCounts()
    for entry in imported.get("holdings", []) or []:
        if not isinstance(entry, dict):
            counts.skipped += 1
            continue
        hid = str(entry.get("id", "")).strip()
        if not hid:
            counts.skipped += 1
            continue

        if hid in current_index:
            existing = holdings[current_index[hid]]
            if isinstance(existing, dict) and _holding_content_hash(existing) == _holding_content_hash(entry):
                counts.skipped += 1
                continue
            merged = dict(entry)
            existing_prov = _holding_provenance(existing) if isinstance(existing, dict) else {}
            new_prov = dict(_holding_provenance(entry))
            if "ingested_at" in existing_prov and "ingested_at" not in new_prov:
                new_prov["ingested_at"] = existing_prov["ingested_at"]
            if new_prov:
                merged["provenance"] = new_prov
            holdings[current_index[hid]] = merged
            counts.updated += 1
        else:
            holdings.append(entry)
            current_index[hid] = len(holdings) - 1
            counts.inserted += 1

    return portfolio, counts


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _activity_keys(entry: dict[str, Any]) -> list[str]:

    keys: list[str] = []
    idem = _as_text(entry.get("idempotency_key"))
    if idem:
        keys.append(f"idem::{idem}")
    aid = _as_text(entry.get("id"))
    if aid:
        keys.append(f"id::{aid}")
    return keys


def _activity_identity(entry: dict[str, Any]) -> tuple[str, str]:
    aid = _as_text(entry.get("id"))
    idem = _as_text(entry.get("idempotency_key"))
    return aid, idem


def _validate_activity_entry(entry: dict[str, Any], idx: int) -> None:
    missing: list[str] = []
    invalid_types: list[str] = []

    aid = entry.get("id")
    if aid is None:
        missing.append("id")
    elif not isinstance(aid, str):
        invalid_types.append("id")
    elif not aid.strip():
        missing.append("id")

    event_type = _as_text(entry.get("event_type"))
    if not event_type:
        missing.append("event_type")
    effective_at = _as_text(entry.get("effective_at"))
    if not effective_at:
        missing.append("effective_at")

    idem = entry.get("idempotency_key")
    if idem is not None and not isinstance(idem, str):
        invalid_types.append("idempotency_key")

    if missing:
        rendered = ", ".join(missing)
        raise ValueError(f"Invalid imported activity at index {idx}: missing {rendered}")
    if invalid_types:
        rendered = ", ".join(invalid_types)
        raise ValueError(
            f"Invalid imported activity at index {idx}: non-string fields {rendered}"
        )


def merge_activities(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> tuple[dict[str, Any], MergeCounts]:
    activities = portfolio.get("activities")
    if not isinstance(activities, list):
        activities = []
        portfolio["activities"] = activities

    current_index: dict[str, int] = {}
    id_index: dict[str, int] = {}
    idem_index: dict[str, int] = {}
    for i, item in enumerate(activities):
        if not isinstance(item, dict):
            continue
        aid, idem = _activity_identity(item)
        if aid:
            id_index.setdefault(aid, i)
        if idem:
            idem_index.setdefault(idem, i)
        for key in _activity_keys(item):
            current_index.setdefault(key, i)

    counts = MergeCounts()
    for idx, entry in enumerate(imported.get("activities", []) or []):
        if not isinstance(entry, dict):
            counts.skipped += 1
            continue

        _validate_activity_entry(entry, idx)

        keys = _activity_keys(entry)
        if not keys:
            counts.skipped += 1
            continue

        normalized = dict(entry)
        normalized.setdefault("status", "posted")
        aid, idem = _activity_identity(normalized)

        matched_pos = None
        if aid and aid in id_index:
            matched_pos = id_index[aid]
        if matched_pos is None and idem and idem in idem_index:
            matched_pos = idem_index[idem]
        if matched_pos is None:
            matched_pos = next((current_index[k] for k in keys if k in current_index), None)
        if matched_pos is not None:
            existing = activities[matched_pos]
            existing_norm = dict(existing) if isinstance(existing, dict) else {}
            existing_norm.setdefault("status", "posted")
            if isinstance(existing, dict):
                if existing.get("idempotency_key") and not normalized.get("idempotency_key"):
                    normalized["idempotency_key"] = existing["idempotency_key"]
                if existing.get("id") and not normalized.get("id"):
                    normalized["id"] = existing["id"]
            normalized_id, normalized_idem = _activity_identity(normalized)
            if _activity_content_hash(existing_norm) == _activity_content_hash(normalized):
                if normalized_id:
                    id_index[normalized_id] = matched_pos
                    current_index[f"id::{normalized_id}"] = matched_pos
                if normalized_idem:
                    idem_index[normalized_idem] = matched_pos
                    current_index[f"idem::{normalized_idem}"] = matched_pos
                counts.skipped += 1
                continue
            if isinstance(existing, dict) and existing.get("ingested_at") and not normalized.get("ingested_at"):
                normalized["ingested_at"] = existing["ingested_at"]
            activities[matched_pos] = normalized
            normalized_id, normalized_idem = _activity_identity(normalized)
            if normalized_id:
                id_index[normalized_id] = matched_pos
                current_index[f"id::{normalized_id}"] = matched_pos
            if normalized_idem:
                idem_index[normalized_idem] = matched_pos
                current_index[f"idem::{normalized_idem}"] = matched_pos
            counts.updated += 1
        else:
            activities.append(normalized)
            new_pos = len(activities) - 1
            normalized_id, normalized_idem = _activity_identity(normalized)
            if normalized_id:
                id_index[normalized_id] = new_pos
                current_index[f"id::{normalized_id}"] = new_pos
            if normalized_idem:
                idem_index[normalized_idem] = new_pos
                current_index[f"idem::{normalized_idem}"] = new_pos
            counts.inserted += 1

    return portfolio, counts


def run_import_plugin(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Legacy entrypoint preserved for existing tests."""
    from .plugin_engine.pipeline import run_import_pipeline

    plugin_name = kwargs.pop("plugin_name", None) or (args[0] if len(args) >= 1 else None)
    input_path = kwargs.pop("input_path", None) or (args[1] if len(args) >= 2 else None)
    plugins_root = kwargs.pop("plugins_root", None)
    if plugins_root is None:
        plugins_root = args[2] if len(args) >= 3 else "plugins"
    if plugin_name is None or input_path is None:
        raise TypeError("run_import_plugin requires plugin_name and input_path")
    return run_import_pipeline(plugin_name, plugins_root, input_path)
