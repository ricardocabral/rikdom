"""Validate the experimental connector boundary shared by CLI and fixtures.

This contract isolates caller-owned JSON and limits dispatch to advertised read
operations. It does not sandbox trusted Python or normalize provider data.
"""

from __future__ import annotations

import math
from typing import Any

import pluggy

from .contracts import PluginContext
from .errors import PluginEngineError


CONNECTOR_CONTRACT_VERSION = "1.0"


def json_object(value: Any, label: str) -> dict:
    """Return detached strict JSON, rejecting coercions and non-finite numbers."""
    def copy_json(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError
            return {key: copy_json(child) for key, child in item.items()}
        if isinstance(item, list):
            return [copy_json(child) for child in item]
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float) and math.isfinite(item):
            return item
        raise ValueError

    try:
        if not isinstance(value, dict):
            raise ValueError
        return copy_json(value)
    except (ValueError, RecursionError):
        # Do not include caller data: it may contain secrets or private inputs.
        raise PluginEngineError(f"{label} must be a finite JSON object with string keys") from None


def describe_connector(pm: pluggy.PluginManager, ctx: PluginContext) -> dict:
    """Validate offline capabilities; readOnly is a declaration, not enforcement."""
    result = json_object(pm.hook.connector_describe(ctx=ctx), "Connector description")
    if result.get("contractVersion") != CONNECTOR_CONTRACT_VERSION:
        raise PluginEngineError("Connector description must declare contractVersion '1.0'")
    if result.get("readOnly") is not True:
        raise PluginEngineError("Connector description must declare readOnly true")
    operations = result.get("operations")
    if not isinstance(operations, dict) or not operations or any(
        not name.strip() or not isinstance(details, dict)
        for name, details in operations.items()
    ):
        raise PluginEngineError("Connector operations must map non-empty names to JSON objects")
    return result


def query_connector(
    pm: pluggy.PluginManager, ctx: PluginContext, operation: str, params: dict
) -> dict:
    """Run one declared operation with detached inputs and return raw JSON."""
    if not isinstance(operation, str) or not operation.strip():
        raise PluginEngineError("Connector operation must be a non-empty string")
    request = json_object(params, "Connector parameters")
    description = describe_connector(pm, ctx)
    if operation not in description["operations"]:
        raise PluginEngineError("Connector does not declare operation; use connector describe to list operations")
    result = pm.hook.connector_query(ctx=ctx, operation=operation, params=request)
    return json_object(result, "Connector query result")
