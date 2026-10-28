from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .canonical_key import holding_canonical_key


_RUN_SCOPED_FIELDS = ("import_run_id", "ingested_at")


@dataclass(slots=True)
class MergeCounts:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    collapsed: int = 0
    collapses: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class DiffCounts:
    create: int = 0
    update: int = 0
    noop: int = 0


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


def _strip_run_scoped_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_run_scoped_fields(v)
            for k, v in value.items()
            if k not in _RUN_SCOPED_FIELDS
        }
    if isinstance(value, list):
        return [_strip_run_scoped_fields(v) for v in value]
    return value


def _field_changes(
    before: Any, after: Any, *, prefix: str = ""
) -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        keys = sorted(set(before.keys()) | set(after.keys()))
        for key in keys:
            path = f"{prefix}.{key}" if prefix else key
            if key not in before:
                changes.append({"field": path, "before": None, "after": after[key]})
                continue
            if key not in after:
                changes.append({"field": path, "before": before[key], "after": None})
                continue
            changes.extend(_field_changes(before[key], after[key], prefix=path))
        return changes
    if before != after:
        return [{"field": prefix or "$", "before": before, "after": after}]
    return []


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
    for entity, collection in (("holding", "holdings"), ("tax_lot", "tax_lots")):
        for entry in imported.get(collection, []) or []:
            if not isinstance(entry, dict):
                continue
            prov = dict(_holding_provenance(entry))
            prov.setdefault("source_system", source_system)
            seed = f"{source_system}|{entity}|{entry.get('id', '')}"
            prov.setdefault(
                "idempotency_key", hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
            )
            prov["import_run_id"] = import_run_id
            prov["ingested_at"] = ingested_at
            entry["provenance"] = prov

    for entry in imported.get("activities", []) or []:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("source_system", source_system)
        entry.setdefault(
            "idempotency_key", _idempotency_key_for_activity(entry, source_system)
        )
        entry["import_run_id"] = import_run_id
        entry["ingested_at"] = ingested_at

    return imported


def _merge_asserted_fields(existing: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Apply asserted values recursively; absent values retain prior audit data."""
    merged = copy.deepcopy(existing)
    for key, value in entry.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_asserted_fields(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _merged_holding(existing: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Refresh asserted fields without losing enrichments or regressing a dated position."""
    old_date, new_date = existing.get("as_of"), entry.get("as_of")
    if old_date and new_date:
        try:
            previous = datetime.fromisoformat(old_date.replace("Z", "+00:00"))
            incoming = datetime.fromisoformat(new_date.replace("Z", "+00:00"))
            previous = previous.replace(tzinfo=timezone.utc) if previous.tzinfo is None else previous
            incoming = incoming.replace(tzinfo=timezone.utc) if incoming.tzinfo is None else incoming
            if incoming < previous:
                return copy.deepcopy(existing)
        except (ValueError, TypeError):
            # Validation reports invalid dates; an undated import keeps its existing semantics.
            pass
    return _merge_asserted_fields(existing, entry)


def _canonical_position_match(holdings: list[dict[str, Any]], entry: dict[str, Any]) -> int | None:
    """An instrument key identifies a position only inside an explicit account."""
    key = holding_canonical_key(entry)
    account = entry.get("account_id")
    if not key or not isinstance(account, str) or not account.strip():
        return None
    matches = [i for i, holding in enumerate(holdings)
               if isinstance(holding, dict)
               and holding_canonical_key(holding) == key
               and holding.get("account_id") == account]
    return matches[0] if len(matches) == 1 else None


def merge_holdings(
    portfolio: dict[str, Any],
    imported: dict[str, Any],
    *,
    collapse_canonical: bool = False,
) -> tuple[dict[str, Any], MergeCounts]:
    holdings = portfolio.get("holdings")
    if not isinstance(holdings, list):
        holdings = []
        portfolio["holdings"] = holdings

    current_index: dict[str, int] = {}
    canonical_index: dict[str, int] = {}
    for i, item in enumerate(holdings):
        if not isinstance(item, dict):
            continue
        if item.get("id"):
            current_index[str(item["id"])] = i
        ckey = holding_canonical_key(item)
        if ckey:
            canonical_index.setdefault(ckey, i)

    counts = MergeCounts()
    for entry in imported.get("holdings", []) or []:
        if not isinstance(entry, dict):
            counts.skipped += 1
            continue
        hid = str(entry.get("id", "")).strip()
        if not hid:
            counts.skipped += 1
            continue

        target_pos = current_index.get(hid)
        collapsed_via_key: str | None = None
        if target_pos is None and collapse_canonical:
            ckey = holding_canonical_key(entry)
            match = _canonical_position_match(holdings, entry)
            if ckey and match is not None:
                target_pos = match
                collapsed_via_key = ckey

        if target_pos is not None:
            existing = holdings[target_pos]
            if isinstance(existing, dict) and _holding_content_hash(
                existing
            ) == _holding_content_hash(entry):
                counts.skipped += 1
                continue
            merged = _merged_holding(existing, entry)
            if (
                isinstance(existing, dict)
                and not collapsed_via_key
                and _holding_content_hash(existing) == _holding_content_hash(merged)
            ):
                counts.skipped += 1
                continue
            if collapsed_via_key:
                # Preserve the existing slot's id so downstream references
                # don't break, and record the collapse in metadata.
                old_id = (
                    str(existing.get("id") or "") if isinstance(existing, dict) else ""
                )
                merged["id"] = old_id or hid
                meta = dict(merged.get("metadata") or {})
                collapsed_from = list(meta.get("collapsed_from") or [])
                if hid and hid != merged["id"] and hid not in collapsed_from:
                    collapsed_from.append(hid)
                if collapsed_from:
                    meta["collapsed_from"] = collapsed_from
                meta["canonical_key"] = collapsed_via_key
                merged["metadata"] = meta
                counts.collapsed += 1
                counts.collapses.append(
                    {
                        "canonical_key": collapsed_via_key,
                        "from_id": hid,
                        "into_id": merged["id"],
                    }
                )
            holdings[target_pos] = merged
            current_index[str(merged.get("id") or hid)] = target_pos
            ckey_after = holding_canonical_key(merged)
            if ckey_after:
                canonical_index[ckey_after] = target_pos
            if not collapsed_via_key:
                counts.updated += 1
        else:
            holdings.append(entry)
            new_pos = len(holdings) - 1
            current_index[hid] = new_pos
            ckey_after = holding_canonical_key(entry)
            if ckey_after:
                canonical_index.setdefault(ckey_after, new_pos)
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
        raise ValueError(
            f"Invalid imported activity at index {idx}: missing {rendered}"
        )
    if invalid_types:
        rendered = ", ".join(invalid_types)
        raise ValueError(
            f"Invalid imported activity at index {idx}: non-string fields {rendered}"
        )


def _normalize_activity_for_compare(
    entry: dict[str, Any], existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    normalized = dict(entry)
    normalized.setdefault("status", "posted")
    if existing:
        if existing.get("idempotency_key") and not normalized.get("idempotency_key"):
            normalized["idempotency_key"] = existing["idempotency_key"]
        if existing.get("id") and not normalized.get("id"):
            normalized["id"] = existing["id"]
    return normalized


def _counts_diff_dict(counts: DiffCounts) -> dict[str, int]:
    return {"create": counts.create, "update": counts.update, "noop": counts.noop}


def build_import_diff(
    portfolio: dict[str, Any],
    imported: dict[str, Any],
    *,
    collapse_canonical: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    holdings_counts = DiffCounts()
    activities_counts = DiffCounts()

    holdings = portfolio.get("holdings")
    existing_holdings: list[dict[str, Any]] = (
        holdings if isinstance(holdings, list) else []
    )
    holding_index: dict[str, dict[str, Any]] = {}
    canonical_index: dict[str, dict[str, Any]] = {}
    for item in existing_holdings:
        if not isinstance(item, dict):
            continue
        hid = _as_text(item.get("id"))
        if hid and hid not in holding_index:
            holding_index[hid] = item
        ckey = holding_canonical_key(item)
        if ckey and ckey not in canonical_index:
            canonical_index[ckey] = item

    for entry in imported.get("holdings", []) or []:
        if not isinstance(entry, dict):
            continue
        hid = _as_text(entry.get("id"))
        if not hid:
            continue
        existing = holding_index.get(hid)
        collapsed_via_key: str | None = None
        if existing is None and collapse_canonical:
            ckey = holding_canonical_key(entry)
            match = _canonical_position_match(existing_holdings, entry)
            if ckey and match is not None:
                existing = existing_holdings[match]
                collapsed_via_key = ckey
        if existing is None:
            rows.append(
                {
                    "entity_type": "holding",
                    "id": hid,
                    "operation": "create",
                    "changes": [],
                }
            )
            holdings_counts.create += 1
            continue

        incoming_for_changes = _merged_holding(existing, entry)
        if collapsed_via_key:
            # Mirror merge_holdings collapse semantics in the dry-run diff:
            # the existing slot id is preserved and collapsed_from is recorded.
            incoming_for_changes["id"] = _as_text(existing.get("id")) or hid
            meta = dict(incoming_for_changes.get("metadata") or {})
            collapsed_from = list(meta.get("collapsed_from") or [])
            if hid and hid != incoming_for_changes["id"] and hid not in collapsed_from:
                collapsed_from.append(hid)
            if collapsed_from:
                meta["collapsed_from"] = collapsed_from
            meta["canonical_key"] = collapsed_via_key
            incoming_for_changes["metadata"] = meta

        existing_norm = _strip_run_scoped_fields(existing)
        incoming_norm = _strip_run_scoped_fields(incoming_for_changes)
        if _holding_content_hash(existing) == _holding_content_hash(
            incoming_for_changes
        ):
            rows.append(
                {
                    "entity_type": "holding",
                    "id": hid,
                    "operation": "noop",
                    "changes": [],
                }
            )
            holdings_counts.noop += 1
            continue

        row: dict[str, Any] = {
            "entity_type": "holding",
            "id": hid,
            "operation": "update",
            "changes": _field_changes(existing_norm, incoming_norm),
        }
        if collapsed_via_key:
            row["collapsed_canonical_key"] = collapsed_via_key
            row["collapsed_into_id"] = _as_text(existing.get("id"))
        rows.append(row)
        holdings_counts.update += 1

    activities = portfolio.get("activities")
    existing_activities: list[dict[str, Any]] = (
        activities if isinstance(activities, list) else []
    )
    current_index: dict[str, int] = {}
    id_index: dict[str, int] = {}
    idem_index: dict[str, int] = {}
    for i, item in enumerate(existing_activities):
        if not isinstance(item, dict):
            continue
        aid, idem = _activity_identity(item)
        if aid:
            id_index.setdefault(aid, i)
        if idem:
            idem_index.setdefault(idem, i)
        for key in _activity_keys(item):
            current_index.setdefault(key, i)

    for entry in imported.get("activities", []) or []:
        if not isinstance(entry, dict):
            continue
        keys = _activity_keys(entry)
        if not keys:
            continue
        aid, idem = _activity_identity(entry)
        matched_pos: int | None = None
        if aid and aid in id_index:
            matched_pos = id_index[aid]
        if matched_pos is None and idem and idem in idem_index:
            matched_pos = idem_index[idem]
        if matched_pos is None:
            matched_pos = next(
                (current_index[k] for k in keys if k in current_index), None
            )

        entity_id = aid or idem or f"row-{len(rows)}"
        if matched_pos is None:
            rows.append(
                {
                    "entity_type": "activity",
                    "id": entity_id,
                    "operation": "create",
                    "changes": [],
                }
            )
            activities_counts.create += 1
            continue

        existing = existing_activities[matched_pos]
        existing_norm = dict(existing) if isinstance(existing, dict) else {}
        existing_norm.setdefault("status", "posted")
        incoming_norm = _normalize_activity_for_compare(entry, existing_norm)

        if _activity_content_hash(existing_norm) == _activity_content_hash(
            incoming_norm
        ):
            rows.append(
                {
                    "entity_type": "activity",
                    "id": entity_id,
                    "operation": "noop",
                    "changes": [],
                }
            )
            activities_counts.noop += 1
            continue

        rows.append(
            {
                "entity_type": "activity",
                "id": entity_id,
                "operation": "update",
                "changes": _field_changes(
                    _strip_run_scoped_fields(existing_norm),
                    _strip_run_scoped_fields(incoming_norm),
                ),
            }
        )
        activities_counts.update += 1

    tax_lot_counts = DiffCounts()
    lots = copy.deepcopy(portfolio.get("tax_lots", []) or [])
    for entry in imported.get("tax_lots", []) or []:
        if not isinstance(entry, dict):
            continue
        pos = _tax_lot_match(lots, entry)
        merged = (
            copy.deepcopy(entry) if pos is None else _merged_tax_lot(lots[pos], entry)
        )
        changes = (
            []
            if pos is None
            else _field_changes(
                _strip_run_scoped_fields(lots[pos]), _strip_run_scoped_fields(merged)
            )
        )
        operation = "create" if pos is None else ("update" if changes else "noop")
        setattr(tax_lot_counts, operation, getattr(tax_lot_counts, operation) + 1)
        rows.append(
            {
                "entity_type": "tax_lot",
                "id": merged.get("id"),
                "operation": operation,
                "changes": changes,
            }
        )
        if pos is None:
            lots.append(merged)
        else:
            lots[pos] = merged

    summary = {
        "holdings": _counts_diff_dict(holdings_counts),
        "activities": _counts_diff_dict(activities_counts),
    }
    if "tax_lots" in imported:
        summary["tax_lots"] = _counts_diff_dict(tax_lot_counts)
    if "statement_observations" in imported:
        observation_counts = DiffCounts()
        observations = {item["id"]: item for item in portfolio.get("statement_observations", [])}
        for entry in imported.get("statement_observations", []) or []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            previous = observations.get(entry["id"])
            merged = entry if previous is None else _merge_asserted_fields(previous, entry)
            operation = "create" if previous is None else ("noop" if previous == merged else "update")
            setattr(observation_counts, operation, getattr(observation_counts, operation) + 1)
            rows.append({"entity_type": "statement_observation", "id": entry["id"], "operation": operation, "changes": [] if previous is None else _field_changes(previous, merged)})
        summary["statement_observations"] = _counts_diff_dict(observation_counts)
    return {
        "summary": summary,
        "rows": rows,
    }


def _tax_lot_match(lots: list[dict[str, Any]], entry: dict[str, Any]) -> int | None:
    idem = _holding_provenance(entry).get("idempotency_key")
    matches = [
        i
        for i, lot in enumerate(lots)
        if lot.get("id") == entry.get("id")
        or (idem and _holding_provenance(lot).get("idempotency_key") == idem)
    ]
    if len(matches) > 1:
        raise ValueError(f"Conflicting tax lot identity for '{entry.get('id')}'")
    return matches[0] if matches else None


def _merged_tax_lot(existing: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(existing)
    merged.update(copy.deepcopy(entry))
    merged["id"] = existing["id"]
    for key in ("provenance", "metadata", "extensions"):
        if isinstance(existing.get(key), dict) and isinstance(entry.get(key), dict):
            merged[key] = {**copy.deepcopy(existing[key]), **copy.deepcopy(entry[key])}
    return merged


def _renamed_tax_lot_reference_errors(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> list[str]:
    """Reject references to importer IDs that stable lot matching would discard."""
    lots = copy.deepcopy(portfolio.get("tax_lots", []) or [])
    renamed: dict[str, str] = {}
    for entry in imported.get("tax_lots", []) or []:
        if not isinstance(entry, dict):
            continue
        pos = _tax_lot_match(lots, entry)
        if pos is None:
            lots.append(copy.deepcopy(entry))
        else:
            if entry.get("id") != lots[pos].get("id"):
                renamed[str(entry.get("id"))] = str(lots[pos].get("id"))
            lots[pos] = _merged_tax_lot(lots[pos], entry)
    errors: list[str] = []
    for activity in imported.get("activities", []) or []:
        if not isinstance(activity, dict):
            continue
        groups = [activity.get("tax_lot_ids", [])]
        action = activity.get("corporate_action")
        if isinstance(action, dict) and isinstance(action.get("legs"), list):
            groups.extend(
                leg.get("tax_lot_ids", [])
                for leg in action["legs"]
                if isinstance(leg, dict)
            )
        for refs in groups:
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, str) and ref in renamed:
                    errors.append(
                        f"Activity '{activity.get('id')}' references renamed tax lot '{ref}'; use stable tax lot ID '{renamed[ref]}'"
                    )
    return errors


def merge_statement_observations(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> tuple[dict[str, Any], MergeCounts]:
    """Retain source observations independently of mutable current positions.

    A source identity is immutable. A revised extraction can enrich the same
    source, but cannot silently substitute a different document for its ID.
    """
    from .validate import _validate_statement_observations

    entries = imported.get("statement_observations", [])
    errors: list[str] = []
    _validate_statement_observations(entries, errors)
    if errors:
        raise ValueError("Invalid statement observations: " + "; ".join(errors))
    observations = copy.deepcopy(portfolio.get("statement_observations", []))
    index = {item["id"]: i for i, item in enumerate(observations)}
    counts = MergeCounts()
    for entry in entries:
        pos = index.get(entry["id"])
        if pos is None:
            index[entry["id"]] = len(observations)
            observations.append(copy.deepcopy(entry))
            counts.inserted += 1
        elif observations[pos]["source"]["sha256"] != entry["source"]["sha256"]:
            raise ValueError(f"Conflicting statement observation '{entry['id']}'")
        elif observations[pos] == _merge_asserted_fields(observations[pos], entry):
            counts.skipped += 1
        else:
            observations[pos] = _merge_asserted_fields(observations[pos], entry)
            counts.updated += 1
    if entries or "statement_observations" in portfolio:
        portfolio["statement_observations"] = observations
    return portfolio, counts


def merge_tax_lots(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> tuple[dict[str, Any], MergeCounts]:
    """Merge asserted lots by stable identity, preserving references and omitted audit data.

    Validate every incoming row before mutation. No quantity or basis is inferred.
    """
    from .validate import _validate_tax_lots

    entries = imported.get("tax_lots", [])
    if not isinstance(entries, list):
        raise ValueError("Imported tax_lots must be an array")
    holding_ids = {
        h["id"]
        for h in portfolio.get("holdings", [])
        if isinstance(h, dict) and isinstance(h.get("id"), str)
    }
    errors: list[str] = []
    _validate_tax_lots(entries, holding_ids, errors)
    for entry in entries:
        if isinstance(entry, dict) and entry.get("holding_id") not in holding_ids:
            errors.append(
                f"tax_lot holding_id '{entry.get('holding_id')}' not in holdings"
            )
    if errors:
        raise ValueError("Invalid imported tax lots: " + "; ".join(errors))
    reference_errors = _renamed_tax_lot_reference_errors(portfolio, imported)
    if reference_errors:
        raise ValueError("; ".join(reference_errors))
    lots = copy.deepcopy(portfolio.get("tax_lots", []) or [])
    counts = MergeCounts()
    for entry in entries:
        pos = _tax_lot_match(lots, entry)
        if pos is None:
            lots.append(copy.deepcopy(entry))
            counts.inserted += 1
        else:
            merged = _merged_tax_lot(lots[pos], entry)
            if _holding_content_hash(lots[pos]) == _holding_content_hash(merged):
                counts.skipped += 1
            else:
                lots[pos] = merged
                counts.updated += 1
    if entries or "tax_lots" in portfolio:
        portfolio["tax_lots"] = lots
    return portfolio, counts


def merge_activities(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> tuple[dict[str, Any], MergeCounts]:
    from .activities import validate_activity_import

    validate_activity_import(portfolio, imported)
    imported_activities = list(imported.get("activities", []) or [])
    for idx, entry in enumerate(imported_activities):
        if isinstance(entry, dict):
            _validate_activity_entry(entry, idx)

    current_activities = portfolio.get("activities")
    activities = (
        list(current_activities) if isinstance(current_activities, list) else []
    )

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
    for entry in imported_activities:
        if not isinstance(entry, dict):
            counts.skipped += 1
            continue

        keys = _activity_keys(entry)
        if not keys:
            counts.skipped += 1
            continue

        normalized = _normalize_activity_for_compare(entry)
        aid, idem = _activity_identity(normalized)

        matched_pos = None
        if aid and aid in id_index:
            matched_pos = id_index[aid]
        if matched_pos is None and idem and idem in idem_index:
            matched_pos = idem_index[idem]
        if matched_pos is None:
            matched_pos = next(
                (current_index[k] for k in keys if k in current_index), None
            )
        if matched_pos is not None:
            existing = activities[matched_pos]
            existing_norm = dict(existing) if isinstance(existing, dict) else {}
            existing_norm.setdefault("status", "posted")
            if isinstance(existing, dict):
                normalized = _normalize_activity_for_compare(normalized, existing)
            normalized_id, normalized_idem = _activity_identity(normalized)
            if _activity_content_hash(existing_norm) == _activity_content_hash(
                normalized
            ):
                if normalized_id:
                    id_index[normalized_id] = matched_pos
                    current_index[f"id::{normalized_id}"] = matched_pos
                if normalized_idem:
                    idem_index[normalized_idem] = matched_pos
                    current_index[f"idem::{normalized_idem}"] = matched_pos
                counts.skipped += 1
                continue
            if (
                isinstance(existing, dict)
                and existing.get("ingested_at")
                and not normalized.get("ingested_at")
            ):
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

    portfolio["activities"] = activities
    return portfolio, counts


def merge_import_diagnostics(portfolio: dict[str, Any], imported: dict[str, Any]) -> dict[str, Any]:
    """Persist source evidence independently of the current holding projection."""
    from .import_preflight import import_diagnostics, validate_import_diagnostics

    diagnostics = copy.deepcopy(import_diagnostics(imported))
    errors = validate_import_diagnostics(diagnostics)
    if errors:
        raise ValueError("; ".join(errors))
    fingerprint = diagnostics.get("document_fingerprint")
    if not fingerprint:
        content = {k: _strip_run_scoped_fields(imported.get(k, [])) for k in ("holdings", "activities", "statement_observations")}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    key = f"{imported.get('provider', 'unknown')}:{fingerprint}"
    state = portfolio.setdefault("extensions", {}).setdefault("rikdom_import_diagnostics", {"version": 1, "statements": {}})
    state["statements"][key] = diagnostics
    return portfolio
