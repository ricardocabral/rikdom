"""Experimental normalized enrichment contract 1.0 (plugin API 1.2).

The host owns query validation and historical selection. Providers supply one
complete MarketSeries document; unvalidated provider lookups cannot enter the
result. No clock, portfolio mutation or network fallback is introduced here.
"""
from __future__ import annotations

from typing import Any

from rikdom.market_series import parse_market_series

from .connectors import json_object
from .contracts import PluginContext
from .errors import PluginEngineError


def validate_enrichment_request(value: Any) -> dict:
    """Detach strict JSON and validate every query before provider execution."""
    request = json_object(value, "Enrichment request")
    if set(request) != {"contract_version", "source", "lookups"} or request["contract_version"] != "1.0":
        raise PluginEngineError("Enrichment request requires contract_version '1.0', source and lookups only")
    if not isinstance(request["source"], dict) or not isinstance(request["lookups"], list):
        raise PluginEngineError("Enrichment source must be an object and lookups an array")
    empty = parse_market_series({"contract_version": "1.0", "series": []})
    for query in request["lookups"]:
        required = {"series_id", "as_of", "max_age_seconds"}
        if not isinstance(query, dict) or not required <= set(query) or set(query) - required - {"retrieved_before"}:
            raise PluginEngineError("Enrichment lookup requires series_id, as_of, max_age_seconds and optional retrieved_before only")
        try:
            empty.lookup(**query)
        except (ValueError, TypeError) as exc:
            raise PluginEngineError(f"Invalid enrichment lookup: {exc}") from exc
    return request


def enrich_market_series(pm, ctx: PluginContext, request: dict) -> dict:
    """Validate provider output and derive lookups from detached series."""
    # Keep the host's validated queries independent of plugin mutations.
    provider_request = json_object(request, "Enrichment request")
    result = json_object(pm.hook.enrichment(ctx=ctx, request=provider_request), "Enrichment response")
    if set(result) != {"contract_version", "market_series"} or result["contract_version"] != "1.0":
        raise PluginEngineError("Enrichment response requires contract_version '1.0' and market_series only")
    try:
        store = parse_market_series(result["market_series"])
    except (ValueError, TypeError) as exc:
        raise PluginEngineError(f"Invalid enrichment market_series: {exc}") from exc
    return {**result, "lookups": [store.lookup(**query) for query in request["lookups"]]}
