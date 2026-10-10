from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from rikdom.plugin_engine.hookspecs import hookimpl


class Plugin:
    @hookimpl
    def source_input(self, ctx, input_path):
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        schema_path = Path(__file__).resolve().parents[2] / "schema" / "plugin-statement.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            raise ValueError(f"Invalid normalized statement at {location}: {error.message}")
        return payload
