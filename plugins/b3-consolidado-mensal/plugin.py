from __future__ import annotations

from pathlib import Path

import importer as importer_impl
from rikdom.plugin_engine.hookspecs import hookimpl


class Plugin:
    @hookimpl
    def source_input(self, ctx, input_path):
        return importer_impl.parse_workbook(Path(input_path))
