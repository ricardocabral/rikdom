from __future__ import annotations

import json
from pathlib import Path
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from rikdom.import_normalization import with_import_diagnostics
from rikdom.plugin_engine.hookspecs import hookimpl


class Plugin:
    @hookimpl
    def source_input(self, ctx, input_path):
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        schema = json.loads(files("rikdom._resources").joinpath("plugin-statement.schema.json").read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            raise ValueError(f"Invalid normalized statement at {location}: {error.message}")
        if "rikdom_import_diagnostics" in payload.get("metadata", {}):
            return payload
        return with_import_diagnostics(
            payload,
            history_coverage=[{
                "scope": "normalized-statement-json:statement",
                "status": "unknown",
                "event_types": [],
                "reasons": ["normalized_input_has_no_declared_history_coverage"],
            }],
            unsupported_events=[],
        )
