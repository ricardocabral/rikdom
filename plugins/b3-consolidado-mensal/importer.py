#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as DefusedET

try:
    from .known_tickers import enrich_holding as _enrich_from_ticker
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parent))
    from known_tickers import enrich_holding as _enrich_from_ticker  # type: ignore[no-redef]

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"x": MAIN_NS, "r": DOC_REL_NS, "pr": PKG_REL_NS}

MAX_WORKBOOK_FILE_SIZE_BYTES = 25 * 1024 * 1024
MAX_XML_ENTRY_SIZE_BYTES = 5 * 1024 * 1024
MAX_XML_COMPRESSION_RATIO = 100.0


@dataclass(frozen=True)
class SheetSpec:
    name: str
    asset_type_id: str
    quantity_header: str
    value_headers: tuple[str, ...]


SHEET_SPECS: tuple[SheetSpec, ...] = (
    SheetSpec(
        name="Posição - Ações",
        asset_type_id="stock",
        quantity_header="Quantidade",
        value_headers=("Valor Atualizado",),
    ),
    SheetSpec(
        name="Posição - BDR",
        asset_type_id="stock",
        quantity_header="Quantidade",
        value_headers=("Valor Atualizado",),
    ),
    SheetSpec(
        name="Posição - ETF",
        asset_type_id="fund",
        quantity_header="Quantidade",
        value_headers=("Valor Atualizado",),
    ),
    SheetSpec(
        name="Posição - Fundos",
        asset_type_id="fund",
        quantity_header="Quantidade",
        value_headers=("Valor Atualizado",),
    ),
    SheetSpec(
        name="Posição - Renda Fixa",
        asset_type_id="debt_instrument",
        quantity_header="Quantidade",
        value_headers=("Valor Atualizado MTM", "Valor Atualizado CURVA"),
    ),
    SheetSpec(
        name="Posição - Tesouro Direto",
        asset_type_id="debt_instrument",
        quantity_header="Quantidade",
        value_headers=("Valor Atualizado", "Valor líquido", "Valor bruto"),
    ),
)

RENDA_FIXA_PREFIX_TO_ASSET_TYPE: dict[str, str] = {
    "CDB": "cdb",
    "LCA": "lca",
    "LCI": "lci",
    "CRI": "cri",
    "CRA": "cra",
    "DEB": "debenture",
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(text: str) -> str:
    lowered = text.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "unknown"


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def _parse_number(value: Any) -> float | None:
    text = _normalize_text(value)
    if not text or text in {"-", "—", "–"}:
        return None

    text = text.replace("R$", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def _parse_date_br(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    parts = text.split("/")
    if len(parts) != 3:
        return None
    try:
        dd, mm, yyyy = (int(p) for p in parts)
        return date(yyyy, mm, dd).isoformat()
    except ValueError:
        return None


def _extract_isin(value: str) -> str | None:
    match = re.search(r"\b[A-Z]{2}[A-Z0-9]{10}\b", value or "")
    if match:
        return match.group(0)
    return None


def _col_letters_to_idx(ref: str) -> int:
    col = 0
    for ch in ref:
        if not ch.isalpha():
            break
        col = col * 26 + (ord(ch.upper()) - ord("A") + 1)
    return col


def _safe_read_xml_entry(zf: zipfile.ZipFile, member_name: str, *, required: bool) -> bytes | None:
    try:
        info = zf.getinfo(member_name)
    except KeyError:
        if required:
            raise ValueError(f"workbook is incompatible: missing required XML part '{member_name}'") from None
        return None

    if info.file_size > MAX_XML_ENTRY_SIZE_BYTES:
        raise ValueError(
            f"workbook is incompatible: XML part '{member_name}' exceeds "
            f"{MAX_XML_ENTRY_SIZE_BYTES} bytes"
        )
    if info.file_size > 0 and info.compress_size == 0:
        raise ValueError(
            f"workbook is incompatible: XML part '{member_name}' has invalid compression metadata"
        )
    if info.compress_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > MAX_XML_COMPRESSION_RATIO:
            raise ValueError(
                f"workbook is incompatible: XML part '{member_name}' has suspicious compression ratio"
            )

    raw = zf.read(member_name)
    if len(raw) > MAX_XML_ENTRY_SIZE_BYTES:
        raise ValueError(
            f"workbook is incompatible: XML part '{member_name}' exceeds "
            f"{MAX_XML_ENTRY_SIZE_BYTES} bytes"
        )
    return raw


def _parse_xml(raw: bytes, member_name: str):
    try:
        return DefusedET.fromstring(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"workbook is incompatible: invalid XML in '{member_name}'") from exc


def _normalize_target_path(target: str) -> str:
    candidate = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    candidate = candidate.replace("\\", "/")
    parts = [part for part in candidate.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("workbook is incompatible: invalid worksheet path traversal in workbook rels")
    normalized = "/".join(parts)
    if not normalized.startswith("xl/"):
        raise ValueError("workbook is incompatible: invalid worksheet path outside xl/")
    return normalized


def _decode_cell(cell: Any, shared_strings: list[str]) -> str:
    ctype = cell.attrib.get("t")
    if ctype == "inlineStr":
        parts = [t.text or "" for t in cell.findall(".//x:t", NS)]
        return "".join(parts)

    v_el = cell.find("x:v", NS)
    if v_el is None:
        return ""
    raw = v_el.text or ""

    if ctype == "s":
        try:
            idx = int(raw)
        except ValueError:
            return ""
        if 0 <= idx < len(shared_strings):
            return shared_strings[idx]
        return ""

    return raw


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    raw = _safe_read_xml_entry(zf, "xl/sharedStrings.xml", required=False)
    if raw is None:
        return []
    root = _parse_xml(raw, "xl/sharedStrings.xml")
    values: list[str] = []
    for si in root.findall("x:si", NS):
        parts = [t.text or "" for t in si.findall(".//x:t", NS)]
        values.append("".join(parts))
    return values


def _read_sheet_targets(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = _parse_xml(
        _safe_read_xml_entry(zf, "xl/workbook.xml", required=True),
        "xl/workbook.xml",
    )
    rels = _parse_xml(
        _safe_read_xml_entry(zf, "xl/_rels/workbook.xml.rels", required=True),
        "xl/_rels/workbook.xml.rels",
    )

    sheet_entries: list[tuple[str, str]] = []
    for sheet in workbook.findall("x:sheets/x:sheet", NS):
        name = _normalize_text(sheet.attrib.get("name", ""))
        rel_id = sheet.attrib.get(f"{{{DOC_REL_NS}}}id", "")
        if not name or not rel_id:
            continue
        sheet_entries.append((name, rel_id))

    referenced_rel_ids = {rel_id for _, rel_id in sheet_entries}

    rel_by_id: dict[str, str] = {}
    for rel in rels.findall("pr:Relationship", NS):
        rel_id = rel.attrib.get("Id", "")
        rel_type = rel.attrib.get("Type", "")
        target = rel.attrib.get("Target", "")
        if rel_id not in referenced_rel_ids:
            continue
        if not rel_type.endswith("/worksheet"):
            continue
        if not target:
            continue
        rel_by_id[rel_id] = _normalize_target_path(target)

    targets: dict[str, str] = {}
    for name, rel_id in sheet_entries:
        target = rel_by_id.get(rel_id)
        if target:
            targets[name] = target
    return targets


def _read_sheet_rows(
    zf: zipfile.ZipFile,
    sheet_target: str,
    shared_strings: list[str],
) -> tuple[list[dict[str, str]], set[str]]:
    root = _parse_xml(
        _safe_read_xml_entry(zf, sheet_target, required=True),
        sheet_target,
    )
    row_nodes = root.findall("x:sheetData/x:row", NS)
    if not row_nodes:
        return [], set()

    header_row: dict[int, str] | None = None
    header_names: set[str] = set()
    rows: list[dict[str, str]] = []
    for row in row_nodes:
        cols: dict[int, str] = {}
        for cell in row.findall("x:c", NS):
            ref = cell.attrib.get("r", "")
            col_idx = _col_letters_to_idx(ref) if ref else 0
            if col_idx <= 0:
                continue
            cols[col_idx] = _normalize_text(_decode_cell(cell, shared_strings))

        if not cols:
            continue

        if header_row is None:
            header_row = cols
            for header in cols.values():
                header_name = _normalize_text(header)
                if header_name:
                    header_names.add(header_name)
            continue

        mapped: dict[str, str] = {}
        for col_idx, header in header_row.items():
            header_name = _normalize_text(header)
            if not header_name:
                continue
            mapped[header_name] = _normalize_text(cols.get(col_idx, ""))

        if any(v for v in mapped.values()):
            rows.append(mapped)

    return rows, header_names


def _choose_asset_type(spec: SheetSpec, row: dict[str, str]) -> str:
    if spec.name == "Posição - Tesouro Direto":
        return "tesouro_direto"

    if spec.name == "Posição - Renda Fixa":
        product = _normalize_text(row.get("Produto", "")).upper()
        prefix = product.split(" - ", 1)[0]
        return RENDA_FIXA_PREFIX_TO_ASSET_TYPE.get(prefix, spec.asset_type_id)

    if spec.name != "Posição - Fundos":
        return spec.asset_type_id

    ticker = _normalize_text(row.get("Código de Negociação", "")).upper()
    product = _normalize_text(row.get("Produto", "")).upper()
    if (
        ticker.endswith("11")
        and ("FII" in product or "FUNDO IMOB" in product or "INV IMOB" in product)
    ):
        return "reit"
    return "fund"


def _row_id(spec: SheetSpec, row: dict[str, str], label: str) -> str:
    account = _normalize_text(row.get("Conta", ""))
    institution = _normalize_text(row.get("Instituição", ""))
    scope_parts: list[str] = []
    if institution:
        scope_parts.append(_slug(institution))
    if account:
        scope_parts.append(_slug(account))
    base = ":".join(scope_parts) or "global"

    code = (
        _normalize_text(row.get("Código de Negociação", ""))
        or _normalize_text(row.get("Código", ""))
        or _normalize_text(row.get("Código ISIN", ""))
        or _extract_isin(_normalize_text(row.get("Código ISIN / Distribuição", "")))
        or label
    )
    instrument = _slug(code)
    return f"b3:{base}:{_slug(spec.name)}:{instrument}"


def _value_for(spec: SheetSpec, row: dict[str, str]) -> float | None:
    for header in spec.value_headers:
        val = _parse_number(row.get(header, ""))
        if val is not None:
            return val
    return None


def _to_holding(spec: SheetSpec, row: dict[str, str]) -> dict[str, Any] | None:
    label = _normalize_text(row.get("Produto", ""))
    if not label:
        return None
    if label.lower().startswith("total"):
        return None

    market_value = _value_for(spec, row)
    if market_value is None:
        return None

    quantity = _parse_number(row.get(spec.quantity_header, ""))
    holding: dict[str, Any] = {
        "id": _row_id(spec, row, label),
        "asset_type_id": _choose_asset_type(spec, row),
        "label": label,
        "market_value": {"amount": market_value, "currency": "BRL"},
        "jurisdiction": {"country": "BR"},
    }
    if quantity is not None:
        holding["quantity"] = quantity

    identifiers: dict[str, Any] = {}
    ticker = _normalize_text(row.get("Código de Negociação", ""))
    if ticker and ticker != "-":
        identifiers["ticker"] = ticker.upper()

    account = _normalize_text(row.get("Conta", ""))
    if account:
        identifiers["provider_account_id"] = account

    isin = (
        _extract_isin(_normalize_text(row.get("Código ISIN", "")))
        or _extract_isin(_normalize_text(row.get("Código ISIN / Distribuição", "")))
    )
    if isin:
        identifiers["isin"] = isin

    if identifiers:
        holding["identifiers"] = identifiers

    metadata: dict[str, Any] = {
        "source_sheet": spec.name,
        "provider": "b3",
    }
    institution = _normalize_text(row.get("Instituição", ""))
    if institution:
        metadata["institution"] = institution

    row_type = _normalize_text(row.get("Tipo", ""))
    if row_type:
        metadata["instrument_type"] = row_type

    indexer = _normalize_text(row.get("Indexador", ""))
    if indexer:
        metadata["indexer"] = indexer

    issuer = _normalize_text(row.get("Emissor", ""))
    if issuer:
        metadata["issuer"] = issuer

    maturity = _parse_date_br(row.get("Vencimento", ""))
    if maturity:
        metadata["maturity_date"] = maturity

    ref_price = (
        _parse_number(row.get("Preço de Fechamento", ""))
        or _parse_number(row.get("Preço Atualizado MTM", ""))
        or _parse_number(row.get("Preço Atualizado CURVA", ""))
    )
    if ref_price is not None:
        metadata["reference_price"] = ref_price

    holding["metadata"] = metadata
    _enrich_from_ticker(holding)
    return holding


def parse_workbook(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_WORKBOOK_FILE_SIZE_BYTES:
        raise ValueError(
            f"workbook is incompatible: file size exceeds {MAX_WORKBOOK_FILE_SIZE_BYTES} bytes"
        )

    try:
        zf_ctx = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("workbook is incompatible: invalid XLSX container") from exc

    with zf_ctx as zf:
        shared_strings = _read_shared_strings(zf)
        targets = _read_sheet_targets(zf)

        holdings: list[dict[str, Any]] = []
        parsed_sheets: list[str] = []
        for spec in SHEET_SPECS:
            target = targets.get(spec.name)
            if not target:
                continue
            rows, headers = _read_sheet_rows(zf, target, shared_strings)

            missing_required = []
            for header in ("Produto", spec.quantity_header):
                if header not in headers:
                    missing_required.append(header)
            has_value_header = any(header in headers for header in spec.value_headers)
            if missing_required or not has_value_header:
                missing = [f"required={missing_required}"] if missing_required else []
                if not has_value_header:
                    missing.append(f"value_any_of={list(spec.value_headers)}")
                raise ValueError(
                    f"workbook is incompatible: sheet '{spec.name}' is missing columns "
                    f"({', '.join(missing)})"
                )

            parsed_sheets.append(spec.name)
            for row in rows:
                holding = _to_holding(spec, row)
                if holding is not None:
                    holdings.append(holding)

    if not parsed_sheets:
        expected = ", ".join(spec.name for spec in SHEET_SPECS)
        raise ValueError(
            "workbook is incompatible: expected at least one supported B3 position sheet "
            f"({expected})"
        )

    if not holdings:
        raise ValueError(
            "workbook is incompatible: parsed supported B3 position sheets but produced zero holdings"
        )

    return {
        "provider": "b3-consolidado-mensal",
        "generated_at": _now_iso(),
        "base_currency": "BRL",
        "holdings": holdings,
        "metadata": {
            "source_file": path.name,
            "parsed_position_sheets": parsed_sheets,
        },
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <statement.xlsx>", file=sys.stderr)
        return 1

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"input file does not exist: {input_path}", file=sys.stderr)
        return 1

    payload = parse_workbook(input_path)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
