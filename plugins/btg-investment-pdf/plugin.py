from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

from rikdom.plugin_engine.hookspecs import hookimpl

spec = importlib.util.spec_from_file_location(
    "btg_investment_pdf_parser", Path(__file__).with_name("parser.py")
)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class Plugin:
    @hookimpl
    def source_input(self, ctx, input_path):
        del ctx
        path = Path(input_path)
        text = (
            subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            if path.suffix.lower() == ".pdf"
            else path.read_text()
        )
        return parser.parse_statement(text, path)
