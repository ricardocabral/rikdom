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
        payload = importer_impl.parse_statement(Path(input_path))
        return with_import_diagnostics(
            payload,
            history_coverage=[{
                "scope": "irpf-xml:statement",
                "status": "unknown",
                "event_types": [],
                "reasons": ["positions_only_source_does_not_supply_activity_history"],
            }],
            unsupported_events=[],
        )
