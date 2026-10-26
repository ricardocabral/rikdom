from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from rikdom.import_normalization import with_import_diagnostics
from rikdom.plugin_engine.hookspecs import hookimpl


def _load_importer_module():
    importer_path = Path(__file__).with_name("importer.py")
    module_name = f"{__name__}_importer"
    spec = importlib.util.spec_from_file_location(module_name, importer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load importer module from {importer_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


importer_impl = _load_importer_module()


class Plugin:
    @hookimpl
    def source_input(self, ctx, input_path):
        skipped_events = []
        payload = importer_impl.parse_statement(Path(input_path))
        unsupported = list(skipped_events)
        for activity in payload.get("activities", []):
            if activity.get("event_type") == "other":
                unsupported.append({
                    "source_ref": activity.get("source_ref") or "charles-schwab#" + activity["id"],
                    "source_event": activity.get("subtype") or "other",
                    "reason": "source_event_has_no_supported_taxonomy_mapping",
                    "affects_quantity": bool(activity.get("quantity")),
                    "affects_cash": bool(activity.get("money", {}).get("amount")),
                })
        return with_import_diagnostics(
            payload,
            history_coverage=[{
                "scope": "charles-schwab:statement",
                "status": "partial" if unsupported else "unknown",
                "event_types": sorted({a["event_type"] for a in payload.get("activities", []) if a["event_type"] != "other"}),
                "reasons": ["unsupported_source_events" if unsupported else "source_does_not_declare_complete_history"],
            }],
            unsupported_events=unsupported,
        )
