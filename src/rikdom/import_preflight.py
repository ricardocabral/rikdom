from __future__ import annotations

from typing import Any

from .import_normalization import as_text, normalize_currency, normalize_datetime, parse_decimal

_ERROR = "error"
_INFO = "info"


def _source_ref(entry: dict[str, Any]) -> str | None:
    direct = as_text(entry.get("source_ref"))
    if direct:
        return direct
    prov = entry.get("provenance")
    if isinstance(prov, dict):
        nested = as_text(prov.get("source_ref"))
        if nested:
            return nested
    return None


def _row_key(entity_type: str, index: int, entry: dict[str, Any] | None) -> str:
    if isinstance(entry, dict):
        rid = as_text(entry.get("id"))
        if rid:
            return f"{entity_type}:{rid}"
    return f"{entity_type}:#{index}"


def _new_issue(
    *,
    code: str,
    severity: str,
    message: str,
    row_key: str,
    field: str | None = None,
    blocking: bool | None = None,
) -> dict[str, Any]:
    effective_blocking = severity == _ERROR if blocking is None else bool(blocking)
    issue = {
        "code": code,
        "severity": severity,
        "message": message,
        "row_key": row_key,
        "blocking": effective_blocking,
    }
    if field:
        issue["field"] = field
    return issue


def _preflight_rows(imported: dict[str, Any]) -> list[tuple[str, int, dict[str, Any] | None]]:
    rows: list[tuple[str, int, dict[str, Any] | None]] = []
    for entity_type, key in (("holding", "holdings"), ("activity", "activities")):
        values = imported.get(key)
        if not isinstance(values, list):
            continue
        for idx, entry in enumerate(values):
            rows.append((entity_type, idx, entry if isinstance(entry, dict) else None))
    return rows


def _validate_currency_field(
    issues: list[dict[str, Any]],
    *,
    row_key: str,
    value: Any,
    field: str,
) -> None:
    if value is None:
        return
    if normalize_currency(value) is None:
        issues.append(
            _new_issue(
                code="INVALID_CURRENCY",
                severity=_ERROR,
                message=f"Invalid currency at '{field}'",
                row_key=row_key,
                field=field,
            )
        )


def _validate_amount_field(
    issues: list[dict[str, Any]],
    *,
    row_key: str,
    value: Any,
    field: str,
) -> None:
    if value is None:
        return
    if parse_decimal(value) is None:
        issues.append(
            _new_issue(
                code="INVALID_NUMBER",
                severity=_ERROR,
                message=f"Invalid numeric value at '{field}'",
                row_key=row_key,
                field=field,
            )
        )


def _validate_holding(
    entry: dict[str, Any], row_key: str, issues: list[dict[str, Any]]
) -> tuple[str, str]:
    hid = as_text(entry.get("id"))
    if not hid:
        issues.append(
            _new_issue(
                code="MISSING_REQUIRED_FIELD",
                severity=_ERROR,
                message="Holding row is missing required field 'id'",
                row_key=row_key,
                field="id",
            )
        )
    if not as_text(entry.get("asset_type_id")):
        issues.append(
            _new_issue(
                code="MISSING_REQUIRED_FIELD",
                severity=_ERROR,
                message="Holding row is missing required field 'asset_type_id'",
                row_key=row_key,
                field="asset_type_id",
            )
        )
    if not as_text(entry.get("label")):
        issues.append(
            _new_issue(
                code="MISSING_REQUIRED_FIELD",
                severity=_ERROR,
                message="Holding row is missing required field 'label'",
                row_key=row_key,
                field="label",
            )
        )
    market_value = entry.get("market_value")
    if not isinstance(market_value, dict):
        issues.append(
            _new_issue(
                code="MISSING_REQUIRED_FIELD",
                severity=_ERROR,
                message="Holding row is missing object field 'market_value'",
                row_key=row_key,
                field="market_value",
            )
        )
    else:
        _validate_amount_field(
            issues,
            row_key=row_key,
            value=market_value.get("amount"),
            field="market_value.amount",
        )
        _validate_currency_field(
            issues,
            row_key=row_key,
            value=market_value.get("currency"),
            field="market_value.currency",
        )
    return hid, as_text(entry.get("asset_type_id"))


def _validate_activity(
    entry: dict[str, Any], row_key: str, issues: list[dict[str, Any]]
) -> tuple[str, str]:
    aid = as_text(entry.get("id"))
    event_type = as_text(entry.get("event_type"))
    effective_at = as_text(entry.get("effective_at"))

    if not aid:
        issues.append(
            _new_issue(
                code="MISSING_REQUIRED_FIELD",
                severity=_ERROR,
                message="Activity row is missing required field 'id'",
                row_key=row_key,
                field="id",
            )
        )
    if not event_type:
        issues.append(
            _new_issue(
                code="MISSING_REQUIRED_FIELD",
                severity=_ERROR,
                message="Activity row is missing required field 'event_type'",
                row_key=row_key,
                field="event_type",
            )
        )
    if not effective_at:
        issues.append(
            _new_issue(
                code="MISSING_REQUIRED_FIELD",
                severity=_ERROR,
                message="Activity row is missing required field 'effective_at'",
                row_key=row_key,
                field="effective_at",
            )
        )
    elif normalize_datetime(effective_at) is None:
        issues.append(
            _new_issue(
                code="DATE_PARSE_FAILED",
                severity=_ERROR,
                message="Activity 'effective_at' could not be parsed",
                row_key=row_key,
                field="effective_at",
            )
        )

    money = entry.get("money")
    if isinstance(money, dict):
        _validate_amount_field(
            issues,
            row_key=row_key,
            value=money.get("amount"),
            field="money.amount",
        )
        _validate_currency_field(
            issues,
            row_key=row_key,
            value=money.get("currency"),
            field="money.currency",
        )
    fees = entry.get("fees")
    if isinstance(fees, dict):
        _validate_amount_field(
            issues,
            row_key=row_key,
            value=fees.get("amount"),
            field="fees.amount",
        )
        _validate_currency_field(
            issues,
            row_key=row_key,
            value=fees.get("currency"),
            field="fees.currency",
        )
    return aid, as_text(entry.get("idempotency_key"))


def build_preflight_report(portfolio: dict[str, Any], imported: dict[str, Any]) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    existing_holding_ids: set[str] = set()
    for item in portfolio.get("holdings", []) or []:
        if isinstance(item, dict):
            hid = as_text(item.get("id"))
            if hid:
                existing_holding_ids.add(hid)

    existing_activity_ids: set[str] = set()
    existing_activity_idem: set[str] = set()
    for item in portfolio.get("activities", []) or []:
        if not isinstance(item, dict):
            continue
        aid = as_text(item.get("id"))
        if aid:
            existing_activity_ids.add(aid)
        idem = as_text(item.get("idempotency_key"))
        if idem:
            existing_activity_idem.add(idem)

    imported_holding_ids: set[str] = set()
    imported_activity_ids: set[str] = set()
    imported_activity_idem: set[str] = set()

    for entity_type, idx, entry in _preflight_rows(imported):
        row_key = _row_key(entity_type, idx, entry)
        row: dict[str, Any] = {
            "row_key": row_key,
            "entity_type": entity_type,
            "index": idx,
        }
        if isinstance(entry, dict):
            rid = as_text(entry.get("id"))
            if rid:
                row["id"] = rid
            source_ref = _source_ref(entry)
            if source_ref:
                row["source_ref"] = source_ref
        rows_payload.append(row)

        if not isinstance(entry, dict):
            issues.append(
                _new_issue(
                    code="NON_OBJECT_ROW",
                    severity=_ERROR,
                    message=f"{entity_type.capitalize()} row is not a JSON object",
                    row_key=row_key,
                )
            )
            continue

        if entity_type == "holding":
            hid, _ = _validate_holding(entry, row_key, issues)
            if hid:
                if hid in imported_holding_ids:
                    issues.append(
                        _new_issue(
                            code="DUPLICATE_IMPORTED",
                            severity=_ERROR,
                            message=f"Duplicate imported holding id '{hid}'",
                            row_key=row_key,
                            field="id",
                        )
                    )
                imported_holding_ids.add(hid)
                if hid in existing_holding_ids:
                    issues.append(
                        _new_issue(
                            code="DUPLICATE_EXISTING",
                            severity=_INFO,
                            blocking=False,
                            message=f"Holding id '{hid}' already exists and will update or noop",
                            row_key=row_key,
                            field="id",
                        )
                    )
        else:
            aid, idem = _validate_activity(entry, row_key, issues)
            if aid:
                if aid in imported_activity_ids:
                    issues.append(
                        _new_issue(
                            code="DUPLICATE_IMPORTED",
                            severity=_ERROR,
                            message=f"Duplicate imported activity id '{aid}'",
                            row_key=row_key,
                            field="id",
                        )
                    )
                imported_activity_ids.add(aid)
                if aid in existing_activity_ids:
                    issues.append(
                        _new_issue(
                            code="DUPLICATE_EXISTING",
                            severity=_INFO,
                            blocking=False,
                            message=f"Activity id '{aid}' already exists and will update or noop",
                            row_key=row_key,
                            field="id",
                        )
                    )
            if idem:
                if idem in imported_activity_idem:
                    issues.append(
                        _new_issue(
                            code="DUPLICATE_IMPORTED",
                            severity=_ERROR,
                            message=f"Duplicate imported activity idempotency_key '{idem}'",
                            row_key=row_key,
                            field="idempotency_key",
                        )
                    )
                imported_activity_idem.add(idem)
                if idem in existing_activity_idem:
                    issues.append(
                        _new_issue(
                            code="DUPLICATE_EXISTING",
                            severity=_INFO,
                            blocking=False,
                            message=(
                                f"Activity idempotency_key '{idem}' already exists and will "
                                "update or noop"
                            ),
                            row_key=row_key,
                            field="idempotency_key",
                        )
                    )

    blocking_issues = [issue for issue in issues if issue.get("blocking")]
    summary = {
        "rows_total": len(rows_payload),
        "issues_total": len(issues),
        "blocking_issues": len(blocking_issues),
    }
    return {
        "ok": len(blocking_issues) == 0,
        "summary": summary,
        "rows": rows_payload,
        "issues": issues,
    }
