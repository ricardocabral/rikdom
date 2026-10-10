"""BTG layout-text statements: positions and reported acquisition observations.

This parser does not infer purchases, tax lots or activities from position tables.
Complete section text remains available for independently audited event recovery.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import hashlib
from pathlib import Path
import re

PROVIDER = "btg-investment-pdf"
NUMBER = r"(?:-?[\d.]+,\d+|-)"
DATE = r"\d{2}/\d{2}/(?:\d{4}|\d{2})"
HEADING = re.compile(
    r"^(?:Fundo de Investimento - (?:Posição|Detalhamento|Movimentação)|Renda fixa - (?:Posição|Detalhamento|Movimentação)|Renda variável - (?:Posição|Movimentação)|Conta corrente - (?:Posição|Movimentação)|Valores em trânsito -).*$"
)


def _decimal(value):
    return (
        Decimal(0)
        if value == "-"
        else Decimal(value.replace(".", "").replace(",", "."))
    )


def _date(value):
    return (
        datetime.strptime(value, "%d/%m/%Y" if len(value) == 10 else "%d/%m/%y")
        .date()
        .isoformat()
    )


def _timestamp(value):
    return value + "T00:00:00-03:00"


def _money(value):
    return {"amount": float(value), "currency": "BRL"}


def _numbers(line):
    return [_decimal(v) for v in re.findall(r"(?<!\S)" + NUMBER + r"(?!\S)", line)]


def _valuation(price, net, ir=0, iof=0, price_date=None):
    result = {
        "unit_price": _money(price),
        "net_value": _money(net),
        "tax_provisions": [],
    }
    for kind, amount in [("IR", ir), ("IOF", iof)]:
        if amount:
            result["tax_provisions"].append({"tax_type": kind, "money": _money(amount)})
    if price_date:
        result["price_as_of"] = _timestamp(price_date)
    return result


def _coupon(rate, scope):
    result = {"reported_rate": rate, "rate_scope": scope}
    match = re.search(r"([\d.,]+)% do CDI", rate)
    if match:
        result.update(
            indexer="CDI_DI_OVER",
            coupon_type="FLOATING",
            indexer_multiplier_pct=float(_decimal(match[1])),
        )
    else:
        match = re.search(r"(CDI|IPCA|SELIC)\s*\+\s*([\d.,]+)%", rate)
        if match:
            result.update(
                indexer={"CDI": "CDI_DI_OVER"}.get(match[1], match[1]),
                coupon_type="FLOATING",
                floating_spread_pct=float(_decimal(match[2])),
            )
        elif re.fullmatch(r"[\d.,]+%(?: a.a.)?", rate):
            result.update(
                indexer="PREFIXADO",
                coupon_type="FIXED",
                fixed_rate_pct=float(_decimal(rate.split("%")[0])),
            )
        elif rate in ("CDI", "IPCA", "SELIC"):
            result.update(
                indexer={"CDI": "CDI_DI_OVER"}.get(rate, rate), coupon_type="FLOATING"
            )
    return result


def _fixed_key(code, maturity, section):
    if code in ("LFT", "NTNB", "NTNB-P", "LTN", "NTNF"):
        return f"{code}-{maturity}-" + (
            "tesouro" if "TESOURO DIRETO" in section else "custodia"
        )
    if "Compromissada" in section:
        return f"COMPROMISSADA-{code}-{maturity}"
    return code.split("-", 1)[-1]


def parse_statement(text: str, source_path: str | Path) -> dict:
    """Return full-label BTG statement payload, rejecting unreconciled totals."""
    account_match = re.search(r"Conta investimento\s+(\d+)", text, re.I)
    period = re.search(r"Período de (" + DATE + r") a (" + DATE + r")", text)
    issued = re.search(r"Emitido em (" + DATE + r")\s+(\d{2}:\d{2})", text)
    if not account_match or not period:
        raise ValueError("BTG full-label statement account/period not found")
    account = account_match[1].lstrip("0") or "0"
    start, end = map(_date, period.groups())
    issued_at = (
        _date(issued[1]) + "T" + issued[2] + ":00-03:00" if issued else _timestamp(end)
    )
    pages = text.rstrip("\f").split("\f")
    sections = []
    current = None
    for page, content in enumerate(pages, 1):
        for line in content.splitlines():
            if HEADING.match(line.strip()):
                current = {
                    "name": line.strip(),
                    "page": page,
                    "text": "",
                    "rows": [],
                    "_line_pages": [],
                }
                sections.append(current)
            if current:
                current["text"] += line + "\n"
                current["_line_pages"].append(page)
    # Sections may span pages; page references for every raw row remain retained.
    balances = []
    expected = {}
    for line in text.splitlines():
        match = re.match(
            r"^\s*(Renda Variável\*?|Renda Fixa\*?|Fundos de Investimento\*?|Valores em Trânsito|Conta Corrente|Total)\s{2,}(.+)$",
            line,
        )
        if not match:
            continue
        values = _numbers(match[2])
        if len(values) == 4 and match[1] not in expected:
            label = match[1].rstrip("*")
            expected[label] = values[2]
            balances.append(
                {
                    "label": label,
                    "as_of": end,
                    "gross_value": _money(values[2]),
                    "net_value": _money(values[3]),
                }
            )
    holdings = []
    by_key = {}

    def add(
        key,
        asset_type,
        label,
        quantity,
        gross,
        section,
        *,
        identifiers=None,
        valuation=None,
        as_of=None,
        extra=None,
    ):
        if key in by_key:
            raise ValueError(f"Duplicate position identity {key}")
        h = {
            "id": f"btg:{account}:{key.lower()}",
            "asset_type_id": asset_type,
            "label": label,
            "market_value": _money(gross),
            "as_of": _timestamp(as_of or end),
            "jurisdiction": {"country": "BR"},
            "identifiers": {"provider_account_id": account, **(identifiers or {})},
            "metadata": {
                "provider": PROVIDER,
                "institution": "BANCO BTG PACTUAL S/A",
                "statement_position_code": key,
                "statement_section": section["name"],
                "statement_category": extra.pop("category")
                if extra and "category" in extra
                else section["name"].split(" - ")[0],
                "statement_as_of": end,
                "statement_account_id": account,
                "source_ref": str(source_path) + "#page=" + str(section["page"]),
            },
        }
        if quantity is not None:
            h["quantity"] = float(quantity)
        if valuation:
            h["valuation"] = valuation
        if extra:
            h["metadata"].update(extra)
        holdings.append(h)
        by_key[key] = h
        return h

    for section in sections:
        name, body = section["name"], section["text"]
        if name == "Fundo de Investimento - Posição - Portfólio de fundos":
            pattern = re.compile(
                r"^\s*(.+?) - (?:Classe|Fundo) CNPJ:\s*([\d./-]+)\*?\s*\n\s*("
                + DATE
                + r")\s+(.+)$",
                re.M,
            )
            for m in pattern.finditer(body):
                values = _numbers(m[4])
                if len(values) == 7:
                    values.insert(0, Decimal(0))
                if len(values) != 8:
                    raise ValueError("Unrecognized fund position row: " + m[0])
                previous, qty, price, gross, ir, iof, net, variation = values
                cnpj = re.sub(r"\D", "", m[2])
                add(
                    cnpj,
                    "fundo_investimento",
                    m[1],
                    qty,
                    gross,
                    section,
                    identifiers={"cnpj": cnpj},
                    valuation=_valuation(price, net, ir, iof, _date(m[3])),
                    as_of=_date(m[3]),
                    extra={
                        "category": "Fundos de Investimento",
                        "previous_net_value": _money(previous),
                        "nominal_variation": _money(variation),
                    },
                )
        elif name.startswith("Renda fixa - Posição -"):
            if not re.search(r"Emissor\s*:", body):
                _compact_fixed_positions(section, add)
            # Emissor starts each position block. Position and detail blocks differ.
            for block in re.split(r"(?=\bEmissor\s*:)", body)[1:]:
                issuer = re.search(r"Emissor\s*:\s*\n\s*(.+)", block)
                code = re.search(
                    r"^\s*([A-Z][A-Z0-9-]*)\*?\s+(" + DATE + r")\s+(" + DATE + r")",
                    block,
                    re.M,
                )
                if not code:
                    continue
                row = re.search(
                    r"^\s*:\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s*$",
                    block,
                    re.M,
                )
                net = re.search(
                    r"Saldo Líquido R\$\s*:\s*\d*\s*\n\s*(" + NUMBER + r")", block
                )
                if not row or not net:
                    raise ValueError("Unrecognized fixed-income position " + code[1])
                qty, price, gross, ir, iof = map(_decimal, row.groups())
                maturity = _date(code[3])
                key = _fixed_key(code[1], maturity, name)
                prefix = code[1].split("-")[0]
                asset_type = (
                    "compromissada"
                    if "Compromissada" in name
                    else {
                        "CDB": "cdb",
                        "CRA": "cra",
                        "CRI": "cri",
                        "DEB": "debenture",
                        "LCA": "lca",
                        "LCI": "lci",
                    }.get(prefix, "tesouro_direto")
                )
                rate = re.search(
                    r"^\s*((?:CDI|IPCA|SELIC)(?:\s*\+\s*[\d.,]+%)?|[\d.,]+%(?: do CDI| a.a.)?)\s*$",
                    block,
                    re.M,
                )
                code_line = code[0].strip().splitlines()[-1]
                line_index = next(
                    i
                    for i, line in enumerate(body.splitlines())
                    if line.strip().startswith(code_line)
                )
                position_page = section["_line_pages"][line_index]
                h = add(
                    key,
                    asset_type,
                    code[1] + " - " + issuer[1].strip(),
                    qty,
                    gross,
                    section,
                    identifiers={
                        "statement_position_code": code[1].split("-", 1)[-1]
                        if prefix in ("CDB", "CRA", "CRI", "DEB", "LCA", "LCI")
                        else key
                    },
                    valuation=_valuation(price, _decimal(net[1]), ir, iof),
                    extra={
                        "category": "Renda Fixa",
                        "issuer": issuer[1].strip(),
                        "maturity_date": maturity,
                        "issue_date": _date(code[2]),
                        "raw_instrument_code": code[1],
                        "source_page": position_page,
                    },
                )
                h["metadata"]["source_ref"] = (
                    str(source_path) + "#page=" + str(position_page)
                )
                h["fixed_income_profile"] = {"maturity_date": maturity}
                if rate:
                    h["fixed_income_profile"]["coupon"] = _coupon(
                        rate[1], "weighted_average"
                    )
        elif name.startswith("Renda variável - Posição -") and "| Aluguel" in name:
            total_row = re.search(r"Total em Aluguel", body)
            values = []
            if total_row:
                for line in body[total_row.end() :].splitlines():
                    if "SAC:" not in line:
                        values.extend(_numbers(line))
            gross = values[-1] if len(values) >= 2 else Decimal(0)
            if gross:
                add(
                    "lending-accrual",
                    "cash_equivalent",
                    "BTG Remuneração Acumulada de Aluguel",
                    None,
                    gross,
                    section,
                    valuation=_valuation(1, gross),
                    extra={
                        "category": "Renda Variável",
                        "noncash_accrual": True,
                        "loaned_assets_already_in_positions": True,
                    },
                )
        elif name.startswith("Renda variável - Posição -"):
            subtype = name.rsplit(" - ", 1)[-1]
            lines = body.splitlines()
            for line_index, line in enumerate(lines):
                line = re.sub(
                    r"SAC:\s*[\d-]+\s*/\s*Ouvidoria:\s*[\d-]+", "", line
                ).rstrip()
                m = re.match(r"^\s*([A-Z][A-Z0-9]{3}\d{1,2})\*?\s{2,}(.+)$", line)
                if not m:
                    continue
                tail_pattern = (
                    r"([\d.]+(?:,\d+)?)\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s*$"
                )
                tail = re.search(tail_pattern, m[2])
                if not tail and line_index + 1 < len(lines):
                    joined = line + "  " + lines[line_index + 1].strip()
                    tail = re.search(tail_pattern, joined)
                    if tail:
                        line = joined
                        m = re.match(
                            r"^\s*([A-Z][A-Z0-9]{3}\d{1,2})\*?\s{2,}(.+)$", line
                        )
                        tail = re.search(tail_pattern, m[2])
                if not tail:
                    continue
                qty = (
                    _decimal(tail[1])
                    if "," in tail[1]
                    else Decimal(tail[1].replace(".", ""))
                )
                price, pm, gross = map(_decimal, tail.groups()[1:])
                label = m[2][: tail.start()].strip()
                ticker = m[1]
                asset_type = (
                    "reit"
                    if subtype == "Fundos Listados" or "imobili" in subtype.lower()
                    else ("etf_" + ticker.lower() if subtype == "ETF" else "stock")
                )
                h = add(
                    ticker,
                    asset_type,
                    ticker + " - " + label,
                    qty,
                    gross,
                    section,
                    identifiers={"ticker": ticker},
                    valuation=_valuation(price, gross),
                    extra={
                        "category": "Renda Variável",
                        "average_price": float(pm),
                        "instrument_type": subtype,
                    },
                )
                section["rows"].append(
                    {
                        "ticker": ticker,
                        "quantity": float(qty),
                        "gross_value": _money(gross),
                        "raw": line.strip(),
                    }
                )
        elif name == "Conta corrente - Posição":
            m = re.search(r"^\s*(" + DATE + r")\s+(" + NUMBER + r")\s*$", body, re.M)
            if m:
                gross = _decimal(m[2])
                add(
                    "cash",
                    "cash_equivalent",
                    "BTG Conta Corrente",
                    None,
                    gross,
                    section,
                    valuation=_valuation(1, gross),
                    extra={"category": "Conta Corrente"},
                )
        elif name.startswith("Valores em trânsito -"):
            rows = []
            lines = body.splitlines()
            for line_index, line in enumerate(lines):
                line = re.sub(
                    r"SAC:\s*[\d-]+\s*/\s*Ouvidoria:\s*[\d-]+", "", line
                ).rstrip()
                if re.match(r"^\s*(?:" + DATE + r"|N/D)", line) and not re.search(
                    r"(" + NUMBER + r")\s*$", line
                ):
                    for following in lines[line_index + 1 : line_index + 4]:
                        if re.match(r"^\s*(?:" + DATE + r"|N/D)", following):
                            break
                        value = re.search(r"(" + NUMBER + r")\s*$", following)
                        if value:
                            line = line.replace("SAC:", "").rstrip() + "  " + value[1]
                            break
                m = re.match(
                    r"^\s*(" + DATE + r"|N/D)\s{2,}(.+?)\s{2,}(" + NUMBER + r")\s*$",
                    line,
                )
                if m:
                    rows.append(
                        {
                            "settlement_date": _date(m[1]) if m[1] != "N/D" else None,
                            "description": m[2],
                            "money": _money(_decimal(m[3])),
                            "raw": line.strip(),
                        }
                    )
            section["rows"] = rows
            gross = sum((Decimal(str(r["money"]["amount"])) for r in rows), Decimal(0))
            if rows:
                suffix = (
                    ""
                    if name.endswith("Renda Variável")
                    else "-" + name.rsplit(" - ", 1)[-1].lower().replace(" ", "-")
                )
                add(
                    "receivables" + suffix,
                    "cash_equivalent",
                    "BTG Valores em Trânsito - Renda Variável",
                    None,
                    gross,
                    section,
                    valuation=_valuation(1, gross),
                    extra={"category": "Valores em Trânsito", "receivables": rows},
                )

    _attach_acquisitions(sections, by_key, end, source_path)
    for section in sections:
        if "Movimentação" in section["name"]:
            lines = section["text"].splitlines()
            for line_index, line in enumerate(lines):
                m = re.match(r"^\s*(" + DATE + r")(?:\s+(.+))?\s*$", line)
                if not m:
                    continue
                description = m[2] or ""
                raw = line.strip()
                if not description:
                    following = (
                        lines[line_index + 1] if line_index + 1 < len(lines) else ""
                    )
                    previous = lines[line_index - 1] if line_index else ""
                    description = following.strip()
                    raw = "\n".join([previous.strip(), line.strip(), following.strip()])
                columns = re.split(r"\s{2,}", description.strip())
                ticker = re.search(r"\b([A-Z][A-Z0-9]{3}\d{1,2})\b", description)
                section["rows"].append(
                    {
                        "date": _date(m[1]),
                        "description": columns[0],
                        "ticker": ticker[1] if ticker else None,
                        "columns": columns,
                        "numeric_cells": [float(x) for x in _numbers(description)],
                        "page": section["_line_pages"][line_index],
                        "raw": raw,
                    }
                )
        section.pop("_line_pages")
    actual = defaultdict(lambda: Decimal(0))
    for h in holdings:
        actual[h["metadata"]["statement_category"]] += Decimal(
            str(h["market_value"]["amount"])
        )
    for category in [
        "Renda Variável",
        "Renda Fixa",
        "Fundos de Investimento",
        "Valores em Trânsito",
        "Conta Corrente",
    ]:
        if category not in expected or abs(
            actual[category] - expected[category]
        ) > Decimal("0.01"):
            raise ValueError(
                f"Statement reconciliation failed for {category}: parsed {actual[category]}, reported {expected.get(category)}"
            )
    total = sum(actual.values(), Decimal(0))
    if "Total" not in expected or abs(total - expected["Total"]) > Decimal("0.01"):
        raise ValueError(
            f"Statement total reconciliation failed: {total}, reported {expected.get('Total')}"
        )
    path = Path(source_path)
    digest = hashlib.sha256(
        path.read_bytes() if path.is_file() else text.encode()
    ).hexdigest()
    observation = {
        "id": f"btg-statement:{account}:{start}:{end}:{digest[:16]}",
        "provider": PROVIDER,
        "provider_account_id": account,
        "period_start": start,
        "period_end": end,
        "issued_at": issued_at,
        "currency": "BRL",
        "source": {"path": str(path), "sha256": digest, "page_count": len(pages)},
        "balances": balances,
        "sections": sections,
        "metadata": {"format": "full_labels", "category_totals_reconciled": True},
    }
    return {
        "provider": PROVIDER,
        "generated_at": issued_at,
        "base_currency": "BRL",
        "holdings": holdings,
        "activities": [],
        "statement_observations": [observation],
        "metadata": {
            "statement_account_id": account,
            "statement_period": start + "/" + end,
            "statement_as_of": end,
            "ending_account_value": float(total),
            "coverage": "complete_positions",
        },
    }


def _compact_fixed_positions(section, add):
    """Older statements print positions as wrapped horizontal table rows."""
    name, body = section["name"], section["text"]
    body = re.sub(r"(\n\s*[A-Z0-9]\s*\n)(?=\s*BANCO)", r"\1\n", body)
    iof_column = next(
        (line.index("IOF R$") for line in body.splitlines() if "IOF R$" in line), None
    )
    ir_column = next(
        (line.index("IR R$") for line in body.splitlines() if "IR R$" in line), None
    )
    header = next(
        (line for line in body.splitlines() if "Ativo" in line and "Emissão" in line),
        "",
    )
    code_column = header.find("Ativo")
    issue_column = header.find("Emissão")
    for chunk in re.split(r"\n\s*\n", body):
        code = re.search(
            r"\b(CDB[A-Z0-9]+|CRA[A-Z0-9]+|CRI[A-Z0-9]+|DEB-[A-Z0-9]+|LCA-[A-Z0-9]+|LCI-[A-Z0-9]+|NTNB-P|NTNB|LFT|LTN|NTNF)\b",
            chunk,
        )
        dates = re.findall(DATE, chunk)
        instrument = code[1] if code else ""
        if code_column >= 0 and issue_column > code_column:
            column_code = "".join(
                line[code_column:issue_column].strip() for line in chunk.splitlines()
            ).replace(" ", "")
            if re.fullmatch(
                r"(?:CDB-|CRA-|CRI-|DEB-|LCA-|LCI-)?[A-Z0-9-]+", column_code
            ):
                instrument = column_code
        if not instrument or len(dates) < 2:
            continue
        tail = None
        for line in chunk.splitlines():
            # Positions have six trailing quantities/prices/values. IOF may be
            # on the previous visual line when the government issuer wraps.
            tail = re.search(
                r"("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s*$",
                line,
            )
            if tail:
                values = list(map(_decimal, tail.groups()))
                break
            tail = re.search(
                r"("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s+("
                + NUMBER
                + r")\s*$",
                line,
            )
            if tail:
                values = list(map(_decimal, tail.groups()))
                iof_values = []
                if iof_column is not None:
                    for other in chunk.splitlines():
                        if other != line:
                            iof_values.extend(
                                _numbers(other[iof_column : iof_column + 20])
                            )
                values.insert(4, iof_values[-1] if iof_values else Decimal(0))
                break
        if not tail:
            for line in chunk.splitlines():
                tail = re.search(
                    r"("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s*$",
                    line,
                )
                if tail:
                    values = list(map(_decimal, tail.groups()))
                    ir_values = []
                    iof_values = []
                    for other in chunk.splitlines():
                        if other == line:
                            continue
                        if ir_column is not None and iof_column is not None:
                            ir_values.extend(_numbers(other[ir_column:iof_column]))
                        if iof_column is not None:
                            iof_values.extend(
                                _numbers(other[iof_column : iof_column + 20])
                            )
                    values[3:3] = [
                        ir_values[-1] if ir_values else Decimal(0),
                        iof_values[-1] if iof_values else Decimal(0),
                    ]
                    break
        if not tail:
            continue
        qty, price, gross, ir, iof, net = values
        # A final code character can wrap onto its own line in narrow tables.
        suffix = re.search(r"\n\s*([A-Z0-9])\s*(?:\n|$)", chunk)
        if (
            suffix
            and instrument not in ("LFT", "NTNB", "NTNB-P", "LTN", "NTNF")
            and not instrument.endswith(suffix[1])
        ):
            instrument += suffix[1]
        maturity = _date(dates[1])
        key = _fixed_key(instrument, maturity, name)
        product = name.rsplit(" - ", 1)[-1]
        prefix = product.split(" -> ")[0]
        asset_type = (
            "compromissada"
            if "Compromissada" in name
            else {
                "CDB": "cdb",
                "CRA": "cra",
                "CRI": "cri",
                "Debênture": "debenture",
                "LCA": "lca",
                "LCI": "lci",
            }.get(prefix, "tesouro_direto")
        )
        issuer = " ".join(line[:code_column].strip() for line in chunk.splitlines()[:2])
        rate = re.search(
            r"(CDI|IPCA|SELIC)\s*\+\s*([\d.,]+)%|([\d.,]+% a.a.)|([\d.,]+% do CDI)",
            chunk,
        )
        h = add(
            key,
            asset_type,
            instrument + " - " + issuer,
            qty,
            gross,
            section,
            identifiers={"statement_position_code": instrument},
            valuation=_valuation(price, net, ir, iof),
            extra={
                "category": "Renda Fixa",
                "raw_instrument_code": instrument,
                "issuer": issuer,
                "issue_date": _date(dates[0]),
                "maturity_date": maturity,
                "raw_position_row": chunk.strip(),
            },
        )
        h["fixed_income_profile"] = {"maturity_date": maturity}
        if rate:
            h["fixed_income_profile"]["coupon"] = _coupon(rate[0], "weighted_average")


def _attach_acquisitions(sections, holdings, observed, source):
    for section in sections:
        name, body = section["name"], section["text"]
        if name.startswith("Fundo de Investimento - Detalhamento -"):
            cnpj = re.search(r"CNPJ:\s*([\d./-]+)", name)
            h = holdings.get(re.sub(r"\D", "", cnpj[1])) if cnpj else None
            if not h:
                continue
            for line in body.splitlines():
                m = re.match(r"^\s*(" + DATE + r")\s+(.+)$", line)
                if not m:
                    continue
                nums = _numbers(m[2])
                if len(nums) != 7:
                    continue
                qty, price, purchase, gross, ir, iof, net = nums
                line_index = body.splitlines().index(line)
                page = section["_line_pages"][line_index]
                h.setdefault("acquisition_observations", []).append(
                    {
                        "acquired_at": _timestamp(_date(m[1])),
                        "observed_at": h["as_of"],
                        "quantity": float(qty),
                        "unit_price": _money(price),
                        "reported_purchase_value": _money(purchase),
                        "cost_basis_kind": "broker_adjusted_purchase_value",
                        "market_value": _money(gross),
                        "valuation": _valuation(
                            h["valuation"]["unit_price"]["amount"], net, ir, iof
                        ),
                        "source_ref": str(source) + "#page=" + str(page),
                        "metadata": {
                            "raw_row": line.strip(),
                            "statement_section": name,
                            "basis_not_tax_lot": True,
                        },
                    }
                )
        elif name.startswith("Renda fixa - Detalhamento -"):
            for block in re.split(r"(?=\bAtivo\s*:)", body)[1:]:
                code = re.search(
                    r"^\s*([A-Z][A-Z0-9-]*)\*?\s+("
                    + DATE
                    + r")\s+("
                    + DATE
                    + r")\s+("
                    + DATE
                    + r")",
                    block,
                    re.M,
                )
                if not code:
                    continue
                key = _fixed_key(code[1], _date(code[3]), name)
                h = holdings.get(key)
                if not h:
                    continue
                # Header positions differ slightly by product; numeric rows have
                # quantity, purchase price, purchase value, current unit price.
                row = re.search(
                    r"^\s*(?:de liquidez\s*:\s*)?(?:-\s{2,})?(?:(?:CDI|IPCA|SELIC)(?:\s*\+\s*[\d.,]+%)?|[\d.,]+%(?: do CDI| a.a.)?)\s{2,}(.+)$",
                    block,
                    re.M,
                )
                if not row:
                    continue
                nums = _numbers(row[1])
                if len(nums) < 4:
                    continue
                qty, price, purchase, current_price = nums[:4]
                value_row = re.search(
                    r"^\s*("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s+("
                    + NUMBER
                    + r")\s*$",
                    block,
                    re.M,
                )
                code_line = code[0].strip().splitlines()[-1]
                line_index = next(
                    i
                    for i, line in enumerate(body.splitlines())
                    if line.strip().startswith(code_line)
                )
                page = section["_line_pages"][line_index]
                observation = {
                    "acquired_at": _timestamp(_date(code[4])),
                    "observed_at": _timestamp(observed),
                    "quantity": float(qty),
                    "unit_price": _money(price),
                    "reported_purchase_value": _money(purchase),
                    "cost_basis_kind": "reported_purchase_value",
                    "source_ref": str(source) + "#page=" + str(page),
                    "metadata": {"statement_section": name, "raw_block": block.strip()},
                }
                if value_row:
                    gross, ir, iof, net = map(_decimal, value_row.groups())
                    observation["market_value"] = _money(gross)
                    observation["valuation"] = _valuation(current_price, net, ir, iof)
                h.setdefault("acquisition_observations", []).append(observation)
