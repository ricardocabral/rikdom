from __future__ import annotations

import re
from typing import Any


CORE_TOP_LEVEL = {
    "schema_version",
    "schema_uri",
    "profile",
    "settings",
    "asset_type_catalog",
    "holdings",
}


VALID_INSTRUMENT_VALUE_TYPES = {"string", "integer", "number", "boolean"}


CANONICAL_SCHEMA_URI = "https://example.org/rikdom/schema/portfolio.schema.json"
CURRENT_SCHEMA_VERSION = (1, 3, 0)
MIN_COMPATIBLE_SCHEMA_VERSION = (1, 0, 0)


LIABILITY_KINDS = {
    "mortgage",
    "secured_loan",
    "unsecured_loan",
    "student_loan",
    "margin",
    "credit_line",
    "credit_card",
    "tax",
    "other",
}

TAX_LOT_ACQUISITION_KINDS = {
    "buy",
    "transfer_in",
    "dividend_reinvest",
    "split",
    "grant_vest",
    "gift",
    "inheritance",
    "other",
}

_ACCOUNT_ID_RE = re.compile(r"^[a-z0-9_\-]+$")

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.match(value)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _check_schema_compatibility(portfolio: dict[str, Any], errors: list[str]) -> None:
    raw_version = portfolio.get("schema_version")
    if raw_version is None:
        return
    if not isinstance(raw_version, str):
        errors.append("'schema_version' must be a string")
        return

    parsed = _parse_semver(raw_version)
    if parsed is None:
        errors.append(
            f"'schema_version' '{raw_version}' must be semantic version MAJOR.MINOR.PATCH"
        )
        return

    current_major = CURRENT_SCHEMA_VERSION[0]
    if parsed[0] != current_major:
        errors.append(
            f"schema_version '{raw_version}' is incompatible: "
            f"reader supports major {current_major}.x "
            f"(minimum {'.'.join(str(p) for p in MIN_COMPATIBLE_SCHEMA_VERSION)}, "
            f"current {'.'.join(str(p) for p in CURRENT_SCHEMA_VERSION)})"
        )
        return

    if parsed < MIN_COMPATIBLE_SCHEMA_VERSION:
        errors.append(
            f"schema_version '{raw_version}' is below minimum compatible "
            f"{'.'.join(str(p) for p in MIN_COMPATIBLE_SCHEMA_VERSION)}"
        )
        return

    if parsed > CURRENT_SCHEMA_VERSION:
        errors.append(
            f"schema_version '{raw_version}' is newer than current "
            f"{'.'.join(str(p) for p in CURRENT_SCHEMA_VERSION)}; "
            "reader may not understand all fields"
        )

    schema_uri = portfolio.get("schema_uri")
    if isinstance(schema_uri, str) and schema_uri != CANONICAL_SCHEMA_URI:
        errors.append(
            f"schema_uri '{schema_uri}' does not match canonical '{CANONICAL_SCHEMA_URI}'"
        )


def _is_typed_value(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return False


def _collect_instrument_attribute_defs(
    asset_type: dict[str, Any],
    asset_type_index: int,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    attrs = asset_type.get("instrument_attributes")
    if attrs is None:
        return {}
    if not isinstance(attrs, list):
        errors.append(f"asset_type_catalog[{asset_type_index}].instrument_attributes must be an array")
        return {}

    defs_by_id: dict[str, dict[str, Any]] = {}
    for j, item in enumerate(attrs):
        prefix = f"asset_type_catalog[{asset_type_index}].instrument_attributes[{j}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue

        attr_id = str(item.get("id", "")).strip()
        if not attr_id:
            errors.append(f"{prefix}.id is required")
            continue
        if attr_id in defs_by_id:
            errors.append(f"Duplicate instrument attribute id '{attr_id}' in asset_type_catalog[{asset_type_index}]")
            continue

        label = str(item.get("label", "")).strip()
        if not label:
            errors.append(f"{prefix}.label is required")

        value_type = str(item.get("value_type", "")).strip()
        if value_type not in VALID_INSTRUMENT_VALUE_TYPES:
            errors.append(
                f"{prefix}.value_type must be one of: {', '.join(sorted(VALID_INSTRUMENT_VALUE_TYPES))}"
            )
            continue

        enum_values = item.get("enum")
        if enum_values is not None:
            if not isinstance(enum_values, list):
                errors.append(f"{prefix}.enum must be an array when provided")
            else:
                for k, enum_value in enumerate(enum_values):
                    if not _is_typed_value(enum_value, value_type):
                        errors.append(
                            f"{prefix}.enum[{k}] must match value_type '{value_type}'"
                        )

        defs_by_id[attr_id] = item

    return defs_by_id



ECONOMIC_EXPOSURE_SUM_MIN = 99.5
ECONOMIC_EXPOSURE_SUM_MAX = 100.5


def _validate_economic_exposure(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object when provided")
        return
    breakdown = value.get("breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        errors.append(f"{path}.breakdown must be a non-empty array")
        return
    total = 0.0
    for idx, line in enumerate(breakdown):
        if not isinstance(line, dict):
            errors.append(f"{path}.breakdown[{idx}] must be an object")
            continue
        weight = line.get("weight_pct")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            errors.append(f"{path}.breakdown[{idx}].weight_pct must be numeric")
            continue
        if weight < 0 or weight > 100:
            errors.append(
                f"{path}.breakdown[{idx}].weight_pct ({weight}) must be between 0 and 100"
            )
            continue
        total += float(weight)
    if not (ECONOMIC_EXPOSURE_SUM_MIN <= total <= ECONOMIC_EXPOSURE_SUM_MAX):
        errors.append(
            f"{path}.breakdown weight_pct must sum to ~100 "
            f"(got {total}, tolerance {ECONOMIC_EXPOSURE_SUM_MIN}..{ECONOMIC_EXPOSURE_SUM_MAX})"
        )


def _validate_money(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object {{amount, currency}}")
        return
    amount = value.get("amount")
    currency = value.get("currency")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        errors.append(f"{path}.amount must be numeric")
    if not isinstance(currency, str) or len(currency) != 3 or currency != currency.upper():
        errors.append(f"{path}.currency must be ISO-4217 (3 uppercase letters)")


def _validate_account_id(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _ACCOUNT_ID_RE.match(value):
        errors.append(f"{path} must match pattern '^[a-z0-9_\\-]+$'")


def _validate_liabilities(
    liabilities: Any,
    holding_ids: set[str],
    errors: list[str],
) -> None:
    if liabilities is None:
        return
    if not isinstance(liabilities, list):
        errors.append("'liabilities' must be an array when provided")
        return
    seen: set[str] = set()
    for i, liability in enumerate(liabilities):
        prefix = f"liabilities[{i}]"
        if not isinstance(liability, dict):
            errors.append(f"{prefix} must be an object")
            continue
        lid = str(liability.get("id", "")).strip()
        if not lid:
            errors.append(f"{prefix}.id is required")
        elif lid in seen:
            errors.append(f"Duplicate liability id '{lid}'")
        else:
            seen.add(lid)

        kind = liability.get("kind")
        if kind is None:
            errors.append(f"{prefix}.kind is required")
        elif kind not in LIABILITY_KINDS:
            errors.append(
                f"{prefix}.kind '{kind}' must be one of: {', '.join(sorted(LIABILITY_KINDS))}"
            )

        if "balance" not in liability:
            errors.append(f"{prefix}.balance is required")
        else:
            _validate_money(liability.get("balance"), f"{prefix}.balance", errors)

        if "principal_original" in liability:
            _validate_money(
                liability.get("principal_original"),
                f"{prefix}.principal_original",
                errors,
            )

        if "account_id" in liability:
            _validate_account_id(liability.get("account_id"), f"{prefix}.account_id", errors)

        secured_by = liability.get("secured_by_holding_id")
        if isinstance(secured_by, str) and secured_by and holding_ids and secured_by not in holding_ids:
            errors.append(
                f"{prefix}.secured_by_holding_id '{secured_by}' not in holdings"
            )


def _validate_tax_lots(
    tax_lots: Any,
    holding_ids: set[str],
    errors: list[str],
) -> None:
    if tax_lots is None:
        return
    if not isinstance(tax_lots, list):
        errors.append("'tax_lots' must be an array when provided")
        return
    seen: set[str] = set()
    for i, lot in enumerate(tax_lots):
        prefix = f"tax_lots[{i}]"
        if not isinstance(lot, dict):
            errors.append(f"{prefix} must be an object")
            continue

        lot_id = str(lot.get("id", "")).strip()
        if not lot_id:
            errors.append(f"{prefix}.id is required")
        elif lot_id in seen:
            errors.append(f"Duplicate tax_lot id '{lot_id}'")
        else:
            seen.add(lot_id)

        holding_id = str(lot.get("holding_id", "")).strip()
        if not holding_id:
            errors.append(f"{prefix}.holding_id is required")
        elif holding_ids and holding_id not in holding_ids:
            errors.append(f"{prefix}.holding_id '{holding_id}' not in holdings")

        if not lot.get("acquired_at"):
            errors.append(f"{prefix}.acquired_at is required")

        quantity = lot.get("quantity")
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
            errors.append(f"{prefix}.quantity is required and must be numeric")

        if "cost_basis" not in lot:
            errors.append(f"{prefix}.cost_basis is required")
        else:
            _validate_money(lot.get("cost_basis"), f"{prefix}.cost_basis", errors)

        if "unit_cost" in lot:
            _validate_money(lot.get("unit_cost"), f"{prefix}.unit_cost", errors)

        kind = lot.get("acquisition_kind")
        if kind is not None and kind not in TAX_LOT_ACQUISITION_KINDS:
            errors.append(
                f"{prefix}.acquisition_kind '{kind}' must be one of: "
                f"{', '.join(sorted(TAX_LOT_ACQUISITION_KINDS))}"
            )

        if "account_id" in lot:
            _validate_account_id(lot.get("account_id"), f"{prefix}.account_id", errors)

        # disposal consistency
        disposed_at = lot.get("disposed_at")
        disposal_activity_id = lot.get("disposal_activity_id")
        if disposal_activity_id and not disposed_at:
            errors.append(
                f"{prefix}.disposal_activity_id set without disposed_at"
            )


def validate_portfolio(portfolio: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    missing = [k for k in CORE_TOP_LEVEL if k not in portfolio]
    if missing:
        errors.append(f"Missing top-level keys: {', '.join(sorted(missing))}")

    schema_uri = portfolio.get("schema_uri")
    if schema_uri is not None and not isinstance(schema_uri, str):
        errors.append("'schema_uri' must be a string")

    _check_schema_compatibility(portfolio, errors)

    profile = portfolio.get("profile")
    if not isinstance(profile, dict):
        errors.append("'profile' must be an object")
    else:
        for k in ("portfolio_id", "owner_kind", "display_name"):
            if k not in profile:
                errors.append(f"'profile.{k}' is required")

    settings = portfolio.get("settings")
    if not isinstance(settings, dict):
        errors.append("'settings' must be an object")
    elif not settings.get("base_currency"):
        errors.append("'settings.base_currency' is required")

    catalog = portfolio.get("asset_type_catalog")
    if not isinstance(catalog, list):
        errors.append("'asset_type_catalog' must be an array")
        catalog_ids: set[str] = set()
        catalog_attr_defs: dict[str, dict[str, dict[str, Any]]] = {}
    else:
        catalog_ids = set()
        catalog_attr_defs = {}
        for i, asset_type in enumerate(catalog):
            if not isinstance(asset_type, dict):
                errors.append(f"asset_type_catalog[{i}] must be an object")
                continue
            if not asset_type.get("id"):
                errors.append(f"asset_type_catalog[{i}].id is required")
                continue
            type_id = str(asset_type["id"]).strip()
            catalog_ids.add(type_id)
            if not asset_type.get("asset_class"):
                errors.append(f"asset_type_catalog[{i}].asset_class is required")
            if type_id:
                catalog_attr_defs[type_id] = _collect_instrument_attribute_defs(asset_type, i, errors)
            if "economic_exposure" in asset_type:
                _validate_economic_exposure(
                    asset_type.get("economic_exposure"),
                    f"asset_type_catalog[{i}].economic_exposure",
                    errors,
                )

    holdings = portfolio.get("holdings")
    holding_ids: set[str] = set()
    if not isinstance(holdings, list):
        errors.append("'holdings' must be an array")
    else:
        for i, holding in enumerate(holdings):
            if not isinstance(holding, dict):
                errors.append(f"holdings[{i}] must be an object")
                continue
            hid = str(holding.get("id", "")).strip()
            if not hid:
                errors.append(f"holdings[{i}].id is required")
            elif hid in holding_ids:
                errors.append(f"Duplicate holding id '{hid}'")
            else:
                holding_ids.add(hid)

            asset_type_id = str(holding.get("asset_type_id", "")).strip()
            if not asset_type_id:
                errors.append(f"holdings[{i}].asset_type_id is required")
            elif catalog_ids and asset_type_id not in catalog_ids:
                errors.append(
                    f"holdings[{i}].asset_type_id '{asset_type_id}' not in asset_type_catalog"
                )

            if "account_id" in holding:
                _validate_account_id(
                    holding.get("account_id"), f"holdings[{i}].account_id", errors
                )

            instrument_attrs = holding.get("instrument_attributes")
            if instrument_attrs is not None and not isinstance(instrument_attrs, dict):
                errors.append(f"holdings[{i}].instrument_attributes must be an object when provided")
            attrs_obj = instrument_attrs if isinstance(instrument_attrs, dict) else {}
            declared_attrs = catalog_attr_defs.get(asset_type_id, {})
            for attr_id, attr_def in declared_attrs.items():
                if attr_def.get("required") and attr_id not in attrs_obj:
                    errors.append(
                        f"holdings[{i}].instrument_attributes missing required key '{attr_id}' for asset_type_id '{asset_type_id}'"
                    )

            for attr_key, attr_value in attrs_obj.items():
                attr_def = declared_attrs.get(attr_key)
                if attr_def is None:
                    errors.append(
                        f"holdings[{i}].instrument_attributes.{attr_key} not declared for asset_type_id '{asset_type_id}'"
                    )
                    continue

                expected_type = str(attr_def.get("value_type", "")).strip()
                if not _is_typed_value(attr_value, expected_type):
                    errors.append(
                        f"holdings[{i}].instrument_attributes.{attr_key} must be {expected_type}"
                    )
                    continue

                enum_values = attr_def.get("enum")
                if isinstance(enum_values, list) and enum_values and attr_value not in enum_values:
                    errors.append(
                        f"holdings[{i}].instrument_attributes.{attr_key} must be one of {enum_values}"
                    )

            if "economic_exposure" in holding:
                _validate_economic_exposure(
                    holding.get("economic_exposure"),
                    f"holdings[{i}].economic_exposure",
                    errors,
                )

            market_value = holding.get("market_value")
            if not isinstance(market_value, dict):
                errors.append(f"holdings[{i}].market_value is required and must be an object")
            else:
                if not isinstance(market_value.get("amount"), (int, float)):
                    errors.append(f"holdings[{i}].market_value.amount must be numeric")
                currency = market_value.get("currency")
                if not isinstance(currency, str) or len(currency) != 3:
                    errors.append(f"holdings[{i}].market_value.currency must be ISO-4217")

    activities = portfolio.get("activities", [])
    if activities is not None:
        if not isinstance(activities, list):
            errors.append("'activities' must be an array when provided")
        else:
            for i, activity in enumerate(activities):
                if not isinstance(activity, dict):
                    errors.append(f"activities[{i}] must be an object")
                    continue
                for k in ("id", "event_type", "status", "effective_at"):
                    if not activity.get(k):
                        errors.append(f"activities[{i}].{k} is required")

    operations = portfolio.get("operations")
    if operations is not None:
        if not isinstance(operations, dict):
            errors.append("'operations' must be an object when provided")
        else:
            tasks = operations.get("task_catalog", [])
            events = operations.get("task_events", [])

            task_ids: set[str] = set()
            if not isinstance(tasks, list):
                errors.append("'operations.task_catalog' must be an array when provided")
            else:
                for i, task in enumerate(tasks):
                    if not isinstance(task, dict):
                        errors.append(f"operations.task_catalog[{i}] must be an object")
                        continue
                    for k in ("id", "label", "category", "status", "cadence"):
                        if not task.get(k):
                            errors.append(f"operations.task_catalog[{i}].{k} is required")

                    tid = str(task.get("id", "")).strip()
                    if tid:
                        if tid in task_ids:
                            errors.append(f"Duplicate operations task id '{tid}'")
                        task_ids.add(tid)

                    cadence = task.get("cadence")
                    if cadence is not None:
                        if not isinstance(cadence, dict):
                            errors.append(f"operations.task_catalog[{i}].cadence must be an object")
                        elif not cadence.get("frequency"):
                            errors.append(
                                f"operations.task_catalog[{i}].cadence.frequency is required"
                            )

            event_ids: set[str] = set()
            if not isinstance(events, list):
                errors.append("'operations.task_events' must be an array when provided")
            else:
                for i, event in enumerate(events):
                    if not isinstance(event, dict):
                        errors.append(f"operations.task_events[{i}] must be an object")
                        continue
                    for k in ("id", "task_id", "event_type", "occurred_at"):
                        if not event.get(k):
                            errors.append(f"operations.task_events[{i}].{k} is required")

                    eid = str(event.get("id", "")).strip()
                    if eid:
                        if eid in event_ids:
                            errors.append(f"Duplicate operations task event id '{eid}'")
                        event_ids.add(eid)

                    task_id = str(event.get("task_id", "")).strip()
                    if task_id and task_id not in task_ids:
                        errors.append(
                            f"operations.task_events[{i}].task_id '{task_id}' not in operations.task_catalog"
                        )

            if isinstance(tasks, list):
                for i, task in enumerate(tasks):
                    if not isinstance(task, dict):
                        continue
                    last_event_id = str(task.get("last_event_id", "")).strip()
                    if last_event_id and last_event_id not in event_ids:
                        errors.append(
                            f"operations.task_catalog[{i}].last_event_id '{last_event_id}' not in operations.task_events"
                        )

    _validate_liabilities(portfolio.get("liabilities"), holding_ids, errors)
    _validate_tax_lots(portfolio.get("tax_lots"), holding_ids, errors)

    return errors
