from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from rikdom.plugin_engine.pipeline import run_import_pipeline


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
    items: list[str] = []
    for i, name in enumerate(sheet_names, start=1):
        items.append(
            f'<sheet name="{escape(name)}" sheetId="{i}" '
            f'r:id="rId{i}"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(items)}</sheets>'
        "</workbook>"
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    rels: list[str] = []
    for i in range(1, sheet_count + 1):
        rels.append(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
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
    overrides: list[str] = [
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
        zf.writestr("xl/workbook.xml", _workbook_xml([s[0] for s in sheets]))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        for i, (_, headers, rows) in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(headers, rows))


def _write_test_workbook(path: Path) -> None:
    sheets: list[tuple[str, list[str], list[list[object]]]] = [
        (
            "Posição - Ações",
            [
                "Produto",
                "Instituição",
                "Conta",
                "Código de Negociação",
                "Código ISIN / Distribuição",
                "Tipo",
                "Quantidade",
                "Preço de Fechamento",
                "Valor Atualizado",
            ],
            [
                [
                    "PETR4 - PETROLEO BRASILEIRO SA",
                    "BANCO BTG PACTUAL S/A",
                    "12345",
                    "PETR4",
                    "BRPETRACNPR6 - 123",
                    "PN",
                    100,
                    37.12,
                    3712,
                ],
                [
                    "Total",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ],
            ],
        ),
        (
            "Posição - BDR",
            [
                "Produto",
                "Instituição",
                "Conta",
                "Código de Negociação",
                "Código ISIN / Distribuição",
                "Tipo",
                "Quantidade",
                "Preço de Fechamento",
                "Valor Atualizado",
            ],
            [
                [
                    "AMZO34 - AMAZON.COM INC",
                    "BANCO BTG PACTUAL S/A",
                    "12345",
                    "AMZO34",
                    "BRAMZOBDR002 - 104",
                    "BDR",
                    20,
                    55.8,
                    1116,
                ]
            ],
        ),
        (
            "Posição - ETF",
            [
                "Produto",
                "Instituição",
                "Conta",
                "Código de Negociação",
                "Código ISIN / Distribuição",
                "Tipo",
                "Quantidade",
                "Preço de Fechamento",
                "Valor Atualizado",
            ],
            [
                [
                    "IVVB11 - ISHARES S&P 500 FUNDO DE INDICE",
                    "BANCO BTG PACTUAL S/A",
                    "12345",
                    "IVVB11",
                    "BRIVVBCTF001 - 100",
                    "Internacional",
                    10,
                    380.15,
                    3801.5,
                ]
            ],
        ),
        (
            "Posição - Fundos",
            [
                "Produto",
                "Instituição",
                "Conta",
                "Código de Negociação",
                "Código ISIN / Distribuição",
                "Tipo",
                "Quantidade",
                "Preço de Fechamento",
                "Valor Atualizado",
            ],
            [
                [
                    "XPML11 - XP MALLS FDO INV IMOB FII",
                    "BANCO BTG PACTUAL S/A",
                    "12345",
                    "XPML11",
                    "BRXPMLCTF007 - 179",
                    "Cotas",
                    99,
                    102.3,
                    10127.7,
                ]
            ],
        ),
        (
            "Posição - Renda Fixa",
            [
                "Produto",
                "Instituição",
                "Emissor",
                "Código",
                "Indexador",
                "Vencimento",
                "Quantidade",
                "Preço Atualizado MTM",
                "Valor Atualizado MTM",
                "Preço Atualizado CURVA",
                "Valor Atualizado CURVA",
            ],
            [
                [
                    "CDB - BANCO TESTE",
                    "BANCO BTG PACTUAL S/A",
                    "BANCO TESTE S/A",
                    "CDB123ABC",
                    "DI",
                    "14/01/2027",
                    20,
                    "-",
                    "-",
                    50.025,
                    1000.5,
                ]
            ],
        ),
        (
            "Posição - Tesouro Direto",
            [
                "Produto",
                "Instituição",
                "Código ISIN",
                "Indexador",
                "Vencimento",
                "Quantidade",
                "Valor Atualizado",
            ],
            [
                [
                    "Tesouro IPCA+ 2035",
                    "BANCO BTG PACTUAL S/A",
                    "BRSTNCNTB3E2",
                    "IPCA",
                    "15/05/2035",
                    11.37,
                    27192.59,
                ]
            ],
        ),
        (
            "Proventos Recebidos",
            ["Produto", "Pagamento", "Valor líquido"],
            [["PETR4 - PETROBRAS", "26/03/2026", 500]],
        ),
    ]
    _write_workbook(path, sheets)


def _holding_by_ticker(holdings: list[dict], ticker: str) -> dict:
    for item in holdings:
        identifiers = item.get("identifiers", {})
        if isinstance(identifiers, dict) and identifiers.get("ticker") == ticker:
            return item
    raise AssertionError(f"ticker not found: {ticker}")


class B3ConsolidadoMensalPluginTests(unittest.TestCase):
    def test_imports_supported_position_sheets_and_maps_holdings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            statement = Path(tmp) / "relatorio-consolidado-mensal-2026-marco.xlsx"
            _write_test_workbook(statement)

            payload = run_import_pipeline(
                plugin_name="b3-consolidado-mensal",
                plugins_dir="plugins",
                input_path=str(statement),
            )

        self.assertEqual(payload["provider"], "b3-consolidado-mensal")
        self.assertEqual(payload["base_currency"], "BRL")
        self.assertEqual(len(payload["holdings"]), 6)

        holdings = payload["holdings"]

        petr4 = _holding_by_ticker(holdings, "PETR4")
        self.assertEqual(petr4["asset_type_id"], "stock")
        self.assertEqual(petr4["market_value"]["currency"], "BRL")
        self.assertEqual(petr4["identifiers"]["provider_account_id"], "12345")
        self.assertEqual(petr4["jurisdiction"]["country"], "BR")

        amzo34 = _holding_by_ticker(holdings, "AMZO34")
        self.assertEqual(amzo34["asset_type_id"], "stock")

        ivvb11 = _holding_by_ticker(holdings, "IVVB11")
        self.assertEqual(ivvb11["asset_type_id"], "fund")

        xpml11 = _holding_by_ticker(holdings, "XPML11")
        self.assertEqual(xpml11["asset_type_id"], "reit")

        renda_fixa = next(h for h in holdings if h["label"] == "CDB - BANCO TESTE")
        self.assertEqual(renda_fixa["asset_type_id"], "cdb")
        self.assertAlmostEqual(renda_fixa["market_value"]["amount"], 1000.5)
        self.assertEqual(renda_fixa["metadata"]["indexer"], "DI")
        self.assertEqual(renda_fixa["metadata"]["maturity_date"], "2027-01-14")

        tesouro = next(h for h in holdings if h["label"] == "Tesouro IPCA+ 2035")
        self.assertEqual(tesouro["asset_type_id"], "tesouro_direto")
        self.assertEqual(tesouro["identifiers"]["isin"], "BRSTNCNTB3E2")
        self.assertEqual(tesouro["metadata"]["maturity_date"], "2035-05-15")

    def test_row_id_uses_institution_and_account_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            statement = Path(tmp) / "relatorio.xlsx"
            _write_workbook(
                statement,
                [
                    (
                        "Posição - Ações",
                        [
                            "Produto",
                            "Instituição",
                            "Conta",
                            "Código de Negociação",
                            "Quantidade",
                            "Valor Atualizado",
                        ],
                        [
                            ["PETR4 - PETROBRAS", "CORRETORA A", "12345", "PETR4", 10, 1000],
                            ["PETR4 - PETROBRAS", "CORRETORA B", "12345", "PETR4", 20, 2000],
                        ],
                    )
                ],
            )

            payload = run_import_pipeline(
                plugin_name="b3-consolidado-mensal",
                plugins_dir="plugins",
                input_path=str(statement),
            )

        ids = [holding["id"] for holding in payload["holdings"]]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_fails_when_supported_position_sheets_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            statement = Path(tmp) / "incompativel.xlsx"
            _write_workbook(
                statement,
                [
                    (
                        "Proventos Recebidos",
                        ["Produto", "Pagamento", "Valor líquido"],
                        [["PETR4 - PETROBRAS", "26/03/2026", 500]],
                    )
                ],
            )

            with self.assertRaisesRegex(
                ValueError,
                "expected at least one supported B3 position sheet",
            ):
                run_import_pipeline(
                    plugin_name="b3-consolidado-mensal",
                    plugins_dir="plugins",
                    input_path=str(statement),
                )

    def test_fails_when_supported_sheet_has_incompatible_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            statement = Path(tmp) / "incompativel-colunas.xlsx"
            _write_workbook(
                statement,
                [
                    (
                        "Posição - Ações",
                        ["Produto", "Instituição", "Conta", "Código de Negociação"],
                        [["PETR4 - PETROBRAS", "CORRETORA A", "12345", "PETR4"]],
                    )
                ],
            )

            with self.assertRaisesRegex(ValueError, "missing columns"):
                run_import_pipeline(
                    plugin_name="b3-consolidado-mensal",
                    plugins_dir="plugins",
                    input_path=str(statement),
                )

    def test_fails_when_supported_sheet_parses_zero_holdings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            statement = Path(tmp) / "sem-posicoes.xlsx"
            _write_workbook(
                statement,
                [
                    (
                        "Posição - Ações",
                        [
                            "Produto",
                            "Instituição",
                            "Conta",
                            "Código de Negociação",
                            "Quantidade",
                            "Valor Atualizado",
                        ],
                        [["Total", "", "", "", "", ""]],
                    )
                ],
            )

            with self.assertRaisesRegex(ValueError, "produced zero holdings"):
                run_import_pipeline(
                    plugin_name="b3-consolidado-mensal",
                    plugins_dir="plugins",
                    input_path=str(statement),
                )

if __name__ == "__main__":
    unittest.main()
