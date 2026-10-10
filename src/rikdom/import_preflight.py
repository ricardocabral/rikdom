from __future__ import annotations

from typing import Any

from .import_normalization import (
    as_text,
    normalize_currency,
    normalize_datetime,
    parse_decimal,
)

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


def _preflight_rows(
    imported: dict[str, Any],
) -> list[tuple[str, int, dict[str, Any] | None]]:
    rows: list[tuple[str, int, dict[str, Any] | None]] = []
    for entity_type, key in (
        ("holding", "holdings"),
        ("activity", "activities"),
        ("tax_lot", "tax_lots"),
        ("statement_observation", "statement_observations"),
    ):
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
        if market_value.get("amount") is None:
            issues.append(
                _new_issue(
                    code="MISSING_REQUIRED_FIELD",
                    severity=_ERROR,
                    message="Holding row is missing required field 'market_value.amount'",
                    row_key=row_key,
                    field="market_value.amount",
                )
            )
        else:
            _validate_amount_field(
                issues,
                row_key=row_key,
                value=market_value.get("amount"),
                field="market_value.amount",
            )
        if market_value.get("currency") is None:
            issues.append(
                _new_issue(
                    code="MISSING_REQUIRED_FIELD",
                    severity=_ERROR,
                    message="Holding row is missing required field 'market_value.currency'",
                    row_key=row_key,
                    field="market_value.currency",
                )
            )
        else:
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


def build_preflight_report(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for entity_type, key in (
        ("holding", "holdings"),
        ("activity", "activities"),
        ("tax_lot", "tax_lots"),
        ("statement_observation", "statement_observations"),
    ):
        if key in imported and not isinstance(imported.get(key), list):
            issues.append(
                _new_issue(
                    code="INVALID_COLLECTION_TYPE",
                    severity=_ERROR,
                    message=(
                        f"Imported '{key}' must be a list; got "
                        f"{type(imported.get(key)).__name__}"
                    ),
                    row_key=f"{entity_type}:*",
                    field=key,
                )
            )

    valid_imported = dict(imported)
    for key in ("holdings", "activities", "tax_lots", "statement_observations"):
        if not isinstance(valid_imported.get(key), list):
            valid_imported[key] = []
    imported = valid_imported
    from .validate import _validate_statement_observations

    observation_errors: list[str] = []
    _validate_statement_observations(imported.get("statement_observations", []), observation_errors)
    for message in observation_errors:
        issues.append(_new_issue(code="INVALID_STATEMENT_OBSERVATION", severity=_ERROR, message=message, row_key="statement_observation:*"))

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
            from .validate import _validate_holding_observations

            observation_errors: list[str] = []
            _validate_holding_observations(entry, f"holdings[{idx}]", observation_errors)
            for message in observation_errors:
                issues.append(_new_issue(code="INVALID_HOLDING_OBSERVATION", severity=_ERROR, message=message, row_key=row_key))
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
        elif entity_type == "statement_observation":
            observation_errors = []
            existing = next((item for item in portfolio.get("statement_observations", []) if item.get("id") == entry.get("id")), None)
            existing_source = existing.get("source") if existing else None
            incoming_source = entry.get("source")
            if isinstance(existing_source, dict) and isinstance(incoming_source, dict) and existing_source.get("sha256") != incoming_source.get("sha256"):
                observation_errors.append(f"Conflicting statement observation '{entry.get('id')}'")
            for message in observation_errors:
                issues.append(_new_issue(code="INVALID_STATEMENT_OBSERVATION", severity=_ERROR, message=message, row_key=row_key))
        elif entity_type == "tax_lot":
            from .validate import _validate_tax_lots

            known_holdings = existing_holding_ids | {
                as_text(h.get("id"))
                for h in (imported.get("holdings", []) or [])
                if isinstance(h, dict)
            }
            lot_errors: list[str] = []
            _validate_tax_lots([entry], known_holdings, lot_errors)
            if as_text(entry.get("holding_id")) not in known_holdings:
                lot_errors.append("tax_lots[0].holding_id not in holdings")
            for message in lot_errors:
                field = message.split("tax_lots[0].", 1)[-1].split(" ", 1)[0]
                issues.append(
                    _new_issue(
                        code="INVALID_TAX_LOT",
                        severity=_ERROR,
                        message=message,
                        row_key=row_key,
                        field=field,
                    )
                )
            lid = as_text(entry.get("id"))
            duplicates = [
                lot
                for lot in imported.get("tax_lots", [])
                if isinstance(lot, dict) and as_text(lot.get("id")) == lid
            ]
            if lid and len(duplicates) > 1:
                issues.append(
                    _new_issue(
                        code="DUPLICATE_IMPORTED",
                        severity=_ERROR,
                        message=f"Duplicate imported tax lot id '{lid}'",
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

    from .validate import (
        _validate_corporate_action,
        _validate_iso_datetime_field,
        _validate_money,
    )

    known_holdings = existing_holding_ids | {
        as_text(h.get("id"))
        for h in (imported.get("holdings", []) or [])
        if isinstance(h, dict)
    }
    known_lots = {
        as_text(lot.get("id"))
        for lot in [
            *(portfolio.get("tax_lots", []) or []),
            *(imported.get("tax_lots", []) or []),
        ]
        if isinstance(lot, dict)
    }
    for idx, activity in enumerate(imported.get("activities", []) or []):
        if not isinstance(activity, dict):
            continue
        for field in (
            "trade_at",
            "settled_at",
            "cost_basis_adjustment",
            "corporate_action",
        ):
            if field not in activity:
                continue
            field_errors: list[str] = []
            if field in ("trade_at", "settled_at"):
                _validate_iso_datetime_field(
                    activity[field], field, field_errors, required=True
                )
            elif field == "cost_basis_adjustment":
                _validate_money(activity[field], field, field_errors)
            else:
                _validate_corporate_action(
                    activity[field], field, known_holdings, known_lots, field_errors
                )
            for message in field_errors:
                issues.append(
                    _new_issue(
                        code="INVALID_ACTIVITY_FIELD",
                        severity=_ERROR,
                        message=message,
                        row_key=_row_key("activity", idx, activity),
                        field=field,
                    )
                )

    from .plugins import _renamed_tax_lot_reference_errors

    try:
        reference_errors = _renamed_tax_lot_reference_errors(portfolio, imported)
    except ValueError as exc:
        reference_errors = [str(exc)]
    for message in reference_errors:
        issues.append(
            _new_issue(
                code="TAX_LOT_IDENTITY_CONFLICT",
                severity=_ERROR,
                message=message,
                row_key="tax_lot:*",
                field="tax_lot_ids",
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
