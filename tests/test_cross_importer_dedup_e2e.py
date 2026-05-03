from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from xml.sax.saxutils import escape

from rikdom.cli import main as rikdom_main


ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "plugins"


def _col_name(index: int) -> str:
    n = index
    parts: list[str] = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        parts.append(chr(ord("A") + rem))
    return "".join(reversed(parts))


def _cell_xml(ref: str, value: object) -> str:
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _sheet_xml(headers: list[str], rows: list[list[object]]) -> str:
    xml_rows: list[str] = []
    header_cells = "".join(
        _cell_xml(f"{_col_name(i)}1", h) for i, h in enumerate(headers, start=1)
    )
    xml_rows.append(f'<row r="1">{header_cells}</row>')

    for r_index, row in enumerate(rows, start=2):
        cells: list[str] = []
        for c_index, val in enumerate(row, start=1):
            if val in ("", None):
                continue
            cells.append(_cell_xml(f"{_col_name(c_index)}{r_index}", val))
        if cells:
            xml_rows.append(f'<row r="{r_index}">{"".join(cells)}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        "</worksheet>"
    )


def _write_b3_bbdc4_workbook(path: Path) -> None:
    headers = [
        "Produto",
        "Instituição",
        "Conta",
        "Código de Negociação",
        "Código ISIN / Distribuição",
        "Tipo",
        "Quantidade",
        "Preço de Fechamento",
        "Valor Atualizado",
    ]
    rows = [
        [
            "BBDC4 - BCO BRADESCO S.A.",
            "BANCO BTG PACTUAL S/A",
            "12345",
            "BBDC4",
            "BRBBDCACNPR8 - 123",
            "PN",
            10,
            15.0,
            150.0,
        ]
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Posição - Ações" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(headers, rows))


def _write_irpf_bbdc4_xml(path: Path) -> None:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<classe xmlns="http://www.receita.fazenda.gov.br/declaracao" '
        'classeJava="serpro.ppgd.irpf.negocio.DeclaracaoIRPF" '
        'dataHoraSalvamento="15/04/2026 10:00:00">'
        "<contribuinte/>"
        '<bens tipoItens="serpro.ppgd.irpf.negocio.bens.Bem">'
        '<item codigo="01" '
        'codigoNegociacao="BBDC4" '
        'discriminacao="BBDC4 - 10 ACOES PN BANCO BRADESCO" '
        'grupo="03" '
        'indice="00001" '
        'niEmpresa="60.746.948/0001-12" '
        'nomePais="105 - Brasil" '
        'pais="105" '
        'registrado="2" '
        'tipo="T" '
        'valorExercicioAnterior="0,00" '
        'valorExercicioAtual="175,00"/>'
        "</bens>"
        "</classe>",
        encoding="utf-8",
    )


class CrossImporterDedupE2ETests(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> dict:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = rikdom_main(argv)
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(stdout.getvalue())

    def test_b3_then_irpf_bbdc4_collapses_only_when_flag_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            portfolio_path = tmp_path / "portfolio.json"
            b3_path = tmp_path / "b3-bbdc4.xlsx"
            irpf_path = tmp_path / "irpf-bbdc4.xml"
            portfolio_path.write_text(
                json.dumps({"holdings": [], "activities": []}), encoding="utf-8"
            )
            _write_b3_bbdc4_workbook(b3_path)
            _write_irpf_bbdc4_xml(irpf_path)

            b3_payload = self._run_cli(
                [
                    "import-statement",
                    "--portfolio",
                    str(portfolio_path),
                    "--plugin",
                    "b3-consolidado-mensal",
                    "--input",
                    str(b3_path),
                    "--plugins-dir",
                    str(PLUGINS_DIR),
                    "--write",
                    "--import-run-id",
                    "run-b3-bbdc4",
                    "--ingested-at",
                    "2026-05-01T00:00:00Z",
                ]
            )
            self.assertEqual(b3_payload["holdings"]["inserted"], 1)

            b3_portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
            self.assertEqual(len(b3_portfolio["holdings"]), 1)
            b3_holding = b3_portfolio["holdings"][0]
            b3_id = b3_holding["id"]
            self.assertEqual(b3_holding["metadata"]["canonical_key"], "br:acao:bbdc4")

            no_collapse = self._run_cli(
                [
                    "import-statement",
                    "--portfolio",
                    str(portfolio_path),
                    "--plugin",
                    "irpf-xml",
                    "--input",
                    str(irpf_path),
                    "--plugins-dir",
                    str(PLUGINS_DIR),
                    "--dry-run",
                    "--import-run-id",
                    "run-irpf-bbdc4-dry-no-collapse",
                    "--ingested-at",
                    "2026-05-02T00:00:00Z",
                ]
            )
            self.assertEqual(
                no_collapse["dry_run_diff"]["summary"]["holdings"],
                {"create": 1, "update": 0, "noop": 0},
            )
            self.assertNotIn("collapsed", no_collapse["holdings"])

            dry_collapse = self._run_cli(
                [
                    "import-statement",
                    "--portfolio",
                    str(portfolio_path),
                    "--plugin",
                    "irpf-xml",
                    "--input",
                    str(irpf_path),
                    "--plugins-dir",
                    str(PLUGINS_DIR),
                    "--collapse-canonical",
                    "--dry-run",
                    "--import-run-id",
                    "run-irpf-bbdc4-dry-collapse",
                    "--ingested-at",
                    "2026-05-02T00:00:00Z",
                ]
            )
            self.assertEqual(
                dry_collapse["dry_run_diff"]["summary"]["holdings"],
                {"create": 0, "update": 1, "noop": 0},
            )
            row = dry_collapse["dry_run_diff"]["rows"][0]
            self.assertEqual(row["collapsed_canonical_key"], "br:acao:bbdc4")
            self.assertEqual(row["collapsed_into_id"], b3_id)
            changed_fields = {change["field"] for change in row["changes"]}
            self.assertNotIn("id", changed_fields)
            self.assertIn("metadata.collapsed_from", changed_fields)
            self.assertEqual(dry_collapse["holdings"]["collapsed"], 1)
            self.assertEqual(
                dry_collapse["holdings"]["collapses"],
                [
                    {
                        "canonical_key": "br:acao:bbdc4",
                        "from_id": "irpf-0301-tk-bbdc4",
                        "into_id": b3_id,
                    }
                ],
            )

            write_collapse = self._run_cli(
                [
                    "import-statement",
                    "--portfolio",
                    str(portfolio_path),
                    "--plugin",
                    "irpf-xml",
                    "--input",
                    str(irpf_path),
                    "--plugins-dir",
                    str(PLUGINS_DIR),
                    "--collapse-canonical",
                    "--write",
                    "--import-run-id",
                    "run-irpf-bbdc4-write-collapse",
                    "--ingested-at",
                    "2026-05-02T00:00:00Z",
                ]
            )
            self.assertTrue(write_collapse["write"])
            self.assertEqual(write_collapse["holdings"]["collapsed"], 1)

            final_portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
            self.assertEqual(len(final_portfolio["holdings"]), 1)
            final_holding = final_portfolio["holdings"][0]
            self.assertEqual(final_holding["id"], b3_id)
            self.assertEqual(final_holding["asset_type_id"], "acao")
            self.assertEqual(
                final_holding["market_value"], {"amount": 175.0, "currency": "BRL"}
            )
            self.assertEqual(
                final_holding["metadata"]["canonical_key"], "br:acao:bbdc4"
            )
            self.assertIn(
                "irpf-0301-tk-bbdc4", final_holding["metadata"]["collapsed_from"]
            )


if __name__ == "__main__":
    unittest.main()
