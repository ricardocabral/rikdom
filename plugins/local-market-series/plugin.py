"""Read one explicitly supplied local MarketSeries file, without networking."""
from __future__ import annotations

import json
from pathlib import Path

from rikdom.plugin_engine.errors import PluginEngineError
from rikdom.plugin_engine.hookspecs import hookimpl


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


class Plugin:
    @hookimpl
    def enrichment(self, ctx, request):
        source = request["source"]
        if (set(source) != {"path"} or not isinstance(source["path"], str)
                or not source["path"].strip()):
            raise PluginEngineError("Local market series source requires only an explicit non-empty path")
        try:
            with Path(source["path"]).open(encoding="utf-8") as handle:
                document = json.load(handle, object_pairs_hook=_unique_object,
                                     parse_constant=_reject_constant)
        except (OSError, ValueError) as exc:
            raise PluginEngineError(f"Cannot read local market series: {type(exc).__name__}") from exc
        return {"contract_version": "1.0", "market_series": document}
