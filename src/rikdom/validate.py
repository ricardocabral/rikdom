from __future__ import annotations

from typing import Any


CORE_TOP_LEVEL = {
    "schema_version",
    "schema_uri",
    "profile",
    "settings",
    "asset_type_catalog",
    "holdings",
}



def validate_portfolio(portfolio: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    missing = [k for k in CORE_TOP_LEVEL if k not in portfolio]
    if missing:
        errors.append(f"Missing top-level keys: {', '.join(sorted(missing))}")

    schema_uri = portfolio.get("schema_uri")
    if schema_uri is not None and not isinstance(schema_uri, str):
        errors.append("'schema_uri' must be a string")

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
    else:
        catalog_ids = set()
        for i, asset_type in enumerate(catalog):
            if not isinstance(asset_type, dict):
                errors.append(f"asset_type_catalog[{i}] must be an object")
                continue
            if not asset_type.get("id"):
                errors.append(f"asset_type_catalog[{i}].id is required")
                continue
            catalog_ids.add(str(asset_type["id"]))
            if not asset_type.get("asset_class"):
                errors.append(f"asset_type_catalog[{i}].asset_class is required")

    holdings = portfolio.get("holdings")
    if not isinstance(holdings, list):
        errors.append("'holdings' must be an array")
    else:
        holding_ids: set[str] = set()
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
                    if task_id and task_ids and task_id not in task_ids:
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

    return errors
