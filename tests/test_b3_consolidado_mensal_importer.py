from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


def _load_importer_module():
    importer_path = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "b3-consolidado-mensal"
        / "importer.py"
    )
    spec = importlib.util.spec_from_file_location("b3_consolidado_mensal_importer_test", importer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load importer module from {importer_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer_module()


def _find_spec(name: str):
    for spec in importer.SHEET_SPECS:
        if spec.name == name:
            return spec
    raise AssertionError(f"sheet spec not found: {name}")


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
    return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'


def _sheet_xml(headers: list[str], rows: list[list[object]]) -> str:
    xml_rows: list[str] = []
    header_cells = "".join(_cell_xml(f"{_col_name(i)}1", h) for i, h in enumerate(headers, start=1))
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
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        "</worksheet>"
    )


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = [
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(sheet_names, start=1)
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(sheets)}</sheets>'
        "</workbook>"
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    rels = [
        (
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
        for i in range(1, sheet_count + 1)
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(rels)}'
        "</Relationships>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _content_types_xml(sheet_count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]
    for i in range(1, sheet_count + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(overrides)}'
        "</Types>"
    )


def _write_workbook(path: Path, sheets: list[tuple[str, list[str], list[list[object]]]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        zf.writestr("_rels/.rels", _root_rels_xml())
        zf.writestr("xl/workbook.xml", _workbook_xml([name for name, _, _ in sheets]))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        for i, (_, headers, rows) in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(headers, rows))


class B3ConsolidadoMensalImporterHelperTests(unittest.TestCase):
    def test_parse_number_supports_br_and_us_formats(self) -> None:
        self.assertEqual(importer._parse_number("R$ 1.234,56"), 1234.56)
        self.assertEqual(importer._parse_number("1,234.56"), 1234.56)
        self.assertEqual(importer._parse_number("2.000,50"), 2000.5)

    def test_parse_number_rejects_placeholders_and_invalid_values(self) -> None:
        self.assertIsNone(importer._parse_number(""))
        self.assertIsNone(importer._parse_number("-"))
        self.assertIsNone(importer._parse_number("—"))
        self.assertIsNone(importer._parse_number("abc"))

    def test_parse_date_br_returns_iso_or_none(self) -> None:
        self.assertEqual(importer._parse_date_br("14/01/2027"), "2027-01-14")
        self.assertIsNone(importer._parse_date_br("31/02/2027"))
        self.assertIsNone(importer._parse_date_br("2027-01-14"))

    def test_extract_isin_finds_valid_code(self) -> None:
        self.assertEqual(
            importer._extract_isin("BRPETRACNPR6 - 123"),
            "BRPETRACNPR6",
        )
        self.assertIsNone(importer._extract_isin("sem isin aqui"))

    def test_choose_asset_type_handles_renda_fixa_and_fundos_branches(self) -> None:
        spec_rf = _find_spec("Posição - Renda Fixa")
        self.assertEqual(
            importer._choose_asset_type(spec_rf, {"Produto": "LCI - BANCO TESTE"}),
            "lci",
        )
        self.assertEqual(
            importer._choose_asset_type(spec_rf, {"Produto": "OUTRO - BANCO TESTE"}),
            "debt_instrument",
        )

        spec_fundos = _find_spec("Posição - Fundos")
        self.assertEqual(
            importer._choose_asset_type(
                spec_fundos,
                {
                    "Código de Negociação": "XPML11",
                    "Produto": "XP MALLS FDO INV IMOB FII",
                },
            ),
            "reit",
        )
        self.assertEqual(
            importer._choose_asset_type(
                spec_fundos,
                {
                    "Código de Negociação": "ABCD11",
                    "Produto": "FUNDO MULTIMERCADO",
                },
            ),
            "fund",
        )

    def test_row_id_falls_back_to_extracted_isin_and_label(self) -> None:
        spec = _find_spec("Posição - Ações")

        row_with_isin = {
            "Conta": "12345",
            "Código ISIN / Distribuição": "BRPETRACNPR6 - 123",
        }
        self.assertEqual(
            importer._row_id(spec, row_with_isin, "PETR4 - PETROBRAS"),
            "b3:12345:posi-o-a-es:brpetracnpr6",
        )

        row_without_identifiers = {"Instituição": "BANCO BTG PACTUAL S/A"}
        self.assertEqual(
            importer._row_id(spec, row_without_identifiers, "Tesouro Prefixado 2029"),
            "b3:banco-btg-pactual-s-a:posi-o-a-es:tesouro-prefixado-2029",
        )

    def test_to_holding_skips_totals_and_rows_without_market_value(self) -> None:
        spec = _find_spec("Posição - Ações")

        self.assertIsNone(importer._to_holding(spec, {"Produto": "Total"}))
        self.assertIsNone(
            importer._to_holding(
                spec,
                {
                    "Produto": "PETR4 - PETROBRAS",
                    "Quantidade": "100",
                    "Valor Atualizado": "-",
                },
            )
        )

    def test_to_holding_uses_fallbacks_for_identifiers_and_reference_price(self) -> None:
        spec = _find_spec("Posição - Renda Fixa")
        row = {
            "Produto": "CDB - BANCO TESTE",
            "Instituição": "BANCO BTG PACTUAL S/A",
            "Código ISIN / Distribuição": "BRPETRACNPR6 - 123",
            "Quantidade": "-",
            "Valor Atualizado MTM": "-",
            "Valor Atualizado CURVA": "2.000,50",
            "Preço Atualizado MTM": "-",
            "Preço Atualizado CURVA": "100,025",
            "Indexador": "DI",
            "Emissor": "BANCO TESTE S/A",
            "Vencimento": "14/01/2027",
        }

        holding = importer._to_holding(spec, row)
        assert holding is not None

        self.assertEqual(holding["asset_type_id"], "cdb")
        self.assertEqual(holding["market_value"], {"amount": 2000.5, "currency": "BRL"})
        self.assertNotIn("quantity", holding)
        self.assertEqual(holding["identifiers"]["isin"], "BRPETRACNPR6")
        self.assertNotIn("ticker", holding["identifiers"])
        self.assertEqual(holding["metadata"]["reference_price"], 100.025)
        self.assertEqual(holding["metadata"]["indexer"], "DI")
        self.assertEqual(holding["metadata"]["issuer"], "BANCO TESTE S/A")
        self.assertEqual(holding["metadata"]["maturity_date"], "2027-01-14")

    def test_read_sheet_targets_normalizes_absolute_targets(self) -> None:
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Posição - Ações" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="/xl/worksheets/sheet1.xml"/>'
            "</Relationships>"
        )

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "sample.xlsx"
            with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("xl/workbook.xml", workbook_xml)
                zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)

            with zipfile.ZipFile(xlsx_path) as zf:
                targets = importer._read_sheet_targets(zf)

        self.assertEqual(targets["Posição - Ações"], "xl/worksheets/sheet1.xml")

    def test_read_sheet_targets_ignores_unrelated_non_worksheet_relationships(self) -> None:
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Posição - Ações" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rIdCustom1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" '
            'Target="../customXml/item1.xml"/>'
            "</Relationships>"
        )

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "sample.xlsx"
            with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("xl/workbook.xml", workbook_xml)
                zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)

            with zipfile.ZipFile(xlsx_path) as zf:
                targets = importer._read_sheet_targets(zf)

        self.assertEqual(targets["Posição - Ações"], "xl/worksheets/sheet1.xml")

    def test_read_sheet_rows_decodes_shared_string_cells(self) -> None:
        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>'
            '<row r="1">'
            '<c r="A1" t="inlineStr"><is><t>Produto</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>Quantidade</t></is></c>'
            '<c r="C1" t="inlineStr"><is><t>Valor Atualizado</t></is></c>'
            "</row>"
            '<row r="2">'
            '<c r="A2" t="s"><v>0</v></c>'
            '<c r="B2"><v>10</v></c>'
            '<c r="C2"><v>100.5</v></c>'
            "</row>"
            "</sheetData>"
            "</worksheet>"
        )

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "sample.xlsx"
            with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)

            with zipfile.ZipFile(xlsx_path) as zf:
                rows, headers = importer._read_sheet_rows(
                    zf,
                    "xl/worksheets/sheet1.xml",
                    shared_strings=["PETR4 - PETROBRAS"],
                )

        self.assertEqual(len(rows), 1)
        self.assertEqual(headers, {"Produto", "Quantidade", "Valor Atualizado"})
        self.assertEqual(rows[0]["Produto"], "PETR4 - PETROBRAS")
        self.assertEqual(rows[0]["Quantidade"], "10")
        self.assertEqual(rows[0]["Valor Atualizado"], "100.5")

    def test_parse_workbook_rejects_files_without_supported_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "unsupported.xlsx"
            _write_workbook(
                xlsx_path,
                [
                    (
                        "Proventos Recebidos",
                        ["Produto", "Pagamento", "Valor líquido"],
                        [["PETR4", "26/03/2026", 500]],
                    )
                ],
            )
            with self.assertRaisesRegex(ValueError, "expected at least one supported B3 position sheet"):
                importer.parse_workbook(xlsx_path)

    def test_parse_workbook_rejects_missing_required_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "missing-columns.xlsx"
            _write_workbook(
                xlsx_path,
                [
                    (
                        "Posição - Ações",
                        ["Produto", "Valor Atualizado"],
                        [["PETR4 - PETROBRAS", 1200]],
                    )
                ],
            )
            with self.assertRaisesRegex(ValueError, "missing columns"):
                importer.parse_workbook(xlsx_path)

    def test_parse_workbook_rejects_supported_sheet_that_produces_zero_holdings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "zero-holdings.xlsx"
            _write_workbook(
                xlsx_path,
                [
                    (
                        "Posição - Ações",
                        ["Produto", "Quantidade", "Valor Atualizado"],
                        [["Total", "", ""]],
                    )
                ],
            )
            with self.assertRaisesRegex(ValueError, "produced zero holdings"):
                importer.parse_workbook(xlsx_path)

    def test_parse_workbook_rejects_oversized_xml_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "oversized-sheet.xml.xlsx"
            _write_workbook(
                xlsx_path,
                [
                    (
                        "Posição - Ações",
                        ["Produto", "Quantidade", "Valor Atualizado"],
                        [[f"PETR4-{'A' * 8192}", 10, 1234.56]],
                    )
                ],
            )
            with (
                mock.patch.object(importer, "MAX_XML_ENTRY_SIZE_BYTES", 512),
                self.assertRaisesRegex(ValueError, "exceeds"),
            ):
                importer.parse_workbook(xlsx_path)

    def test_safe_read_xml_entry_rejects_invalid_compression_metadata(self) -> None:
        zf = mock.Mock(spec=zipfile.ZipFile)
        zf.getinfo.return_value = zipfile.ZipInfo("xl/workbook.xml")
        zf.getinfo.return_value.file_size = 10
        zf.getinfo.return_value.compress_size = 0

        with self.assertRaisesRegex(ValueError, "invalid compression metadata"):
            importer._safe_read_xml_entry(zf, "xl/workbook.xml", required=True)

    def test_safe_read_xml_entry_rejects_suspicious_compression_ratio(self) -> None:
        zf = mock.Mock(spec=zipfile.ZipFile)
        zf.getinfo.return_value = zipfile.ZipInfo("xl/workbook.xml")
        zf.getinfo.return_value.file_size = 1024
        zf.getinfo.return_value.compress_size = 1

        with self.assertRaisesRegex(ValueError, "suspicious compression ratio"):
            importer._safe_read_xml_entry(zf, "xl/workbook.xml", required=True)

    def test_parse_workbook_rejects_oversized_xlsx_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "oversized-container.xlsx"
            xlsx_path.write_bytes(b"small")

            with (
                mock.patch.object(importer, "MAX_WORKBOOK_FILE_SIZE_BYTES", 1),
                self.assertRaisesRegex(ValueError, "file size exceeds"),
            ):
                importer.parse_workbook(xlsx_path)

    def test_parse_workbook_rejects_invalid_xlsx_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "invalid-container.xlsx"
            xlsx_path.write_text("not-a-zip", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid XLSX container"):
                importer.parse_workbook(xlsx_path)

    def test_parse_workbook_rejects_worksheet_path_traversal(self) -> None:
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Posição - Ações" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="../evil.xml"/>'
            "</Relationships>"
        )

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "path-traversal.xlsx"
            with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("xl/workbook.xml", workbook_xml)
                zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)

            with self.assertRaisesRegex(ValueError, "path traversal"):
                importer.parse_workbook(xlsx_path)

    def test_main_returns_error_without_args(self) -> None:
        with mock.patch.object(importer.sys, "argv", ["importer.py"]):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = importer.main()

        self.assertEqual(code, 1)
        self.assertIn("usage: importer.py <statement.xlsx>", stderr.getvalue())

    def test_main_returns_error_for_missing_file(self) -> None:
        with mock.patch.object(importer.sys, "argv", ["importer.py", "/tmp/does-not-exist.xlsx"]):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = importer.main()

        self.assertEqual(code, 1)
        self.assertIn("input file does not exist", stderr.getvalue())

    def test_main_prints_json_payload_on_success(self) -> None:
        payload = {"provider": "b3-consolidado-mensal", "holdings": []}

        with (
            tempfile.NamedTemporaryFile(suffix=".xlsx") as f,
            mock.patch.object(importer, "parse_workbook", return_value=payload),
            mock.patch.object(importer.sys, "argv", ["importer.py", f.name]),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = importer.main()

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), payload)


if __name__ == "__main__":
    unittest.main()
