#!/usr/bin/env python3
"""Importer for Brazilian IRPF (Imposto de Renda Pessoa Fisica) XML declarations.

Maps the `<bens>/<item>` ("Bens e Direitos") entries from a declaration XML
into the canonical rikdom plugin-statement payload. Asset types are picked
from the default catalog and the BR catalog (`asset-types-br-catalog`).

Reference for the IRPF group/code taxonomy used here:
https://www.gov.br/receitafederal/  (Tabela de Bens e Direitos)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

NS = "{http://www.receita.fazenda.gov.br/declaracao}"

# Brazilian IRPF identifies "Brasil" with country code 105 in its country table.
_IRPF_BRAZIL_CODE = "105"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_brl(raw: str | None) -> float:
    if not raw:
        return 0.0
    s = raw.strip()
    if not s:
        return 0.0
    # Brazilian number format: "1.234.567,89" -> 1234567.89
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_cnpj(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 14:
        return None
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"


def _parse_savedate(raw: str | None) -> tuple[str, int]:
    """Return (ISO timestamp, declaration_year). declaration_year = exercicio."""
    if raw:
        try:
            dt = datetime.strptime(raw.strip(), "%d/%m/%Y %H:%M:%S")
            iso = dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            return iso, dt.year
        except ValueError:
            pass
    return _now_iso(), datetime.now(timezone.utc).year


def _classify(grupo: str, codigo: str, discriminacao: str, ticker: str) -> str:
    """Map IRPF (grupo, codigo) + free-text hints to a rikdom asset_type_id.

    Falls back to 'other' when nothing matches; the caller keeps the raw
    grupo/codigo in metadata so users can still reclassify later.
    """
    d = (discriminacao or "").upper()

    if grupo == "01":
        return "real_estate"
    if grupo == "02":
        return "vehicle"
    if grupo == "03":
        if codigo == "01":
            return "acao"
        if codigo == "02":
            return "private_equity"
        return "other"
    if grupo == "04":
        if codigo == "01":
            return "savings_account"
        if codigo == "02":
            # Group 04.02 normally represents funds subject to periodic
            # taxation, but declarations sometimes use it for explicitly
            # named CDB/RDB and Tesouro Direto positions. Keep those generic
            # types: their statement text is decisive while the strict fund
            # attributes cannot be inferred from this IRPF row.
            if "TESOURO" in d or "LFT" in d or "NTN-B" in d or "LTN" in d:
                return "tesouro_direto"
            if re.search(r"\bCDB\b", d):
                return "cdb"
            if re.search(r"\bRDB\b", d):
                return "debt_instrument"
            return "fundo_investimento"
        if codigo == "03":
            if "TESOURO" in d or "LFT" in d or "NTN-B" in d or "LTN" in d:
                return "tesouro_direto"
            if re.search(r"\bLCI\b", d):
                return "lci"
            if re.search(r"\bLCA\b", d):
                return "lca"
            if re.search(r"\bCDB\b", d):
                return "cdb"
            if re.search(r"\bCRA\b", d):
                return "cra"
            if re.search(r"\bCRI\b", d):
                return "cri"
            if "DEBENT" in d and ("INFRA" in d or "12.431" in d or "14.801" in d):
                return "debenture_infra"
            if "DEBENT" in d:
                return "debenture"
            return "fixed_income"
        if codigo == "04":
            return "bdr" if ticker else "foreign_security"
        if codigo == "05":
            return "crypto"
        return "other"
    if grupo == "05":
        return "crypto"
    if grupo == "06":
        return "cash_equivalent"
    if grupo == "07":
        if codigo == "01":
            return "fundo_investimento"
        if codigo == "02":
            return "fiagro_cota"
        if codigo == "03":
            return "fii"
        if codigo == "04":
            return "fundo_investimento"
        return "fundo_investimento"
    if grupo == "08":
        return "acao"
    if grupo == "09":
        return "other"
    if grupo == "10":
        return "crypto"
    if grupo == "99":
        if codigo == "06":
            return "previdencia_privada"
        return "other"
    return "other"


def _norm_text(text: str | None) -> str:
    """Uppercase, collapse whitespace, strip punctuation noise.

    Used as a last-resort fingerprint of `discriminacao` when nothing more
    structured is available. Not strong against user edits, but keeps re-runs
    of the same declaration deterministic and survives small whitespace
    differences.
    """
    if not text:
        return ""
    s = re.sub(r"\s+", " ", text.strip().upper())
    return re.sub(r"[^A-Z0-9 /.\-]", "", s)


def _stable_holding_id(item: ET.Element, *, grupo: str, codigo: str) -> str:
    """Year-agnostic stable id so cross-year imports dedup correctly.

    Priority of identifiers (most stable first):

    1. `codigoNegociacao` (B3 ticker) — invariant for stocks/FIIs/ETFs/BDRs.
    2. `codigoAltcoin` / `codigoStablecoin` — crypto unique codes.
    3. Fund CNPJ (groups 07.* and 04.02) — identifies the fund itself.
    4. Bank coordinates `banco/agencia/conta` (group 06) — stable per account.
    5. Pension provider CNPJ + plan label hash (group 99.06).
    6. Fallback: blake2s digest of `(grupo, codigo, cnpj, normalized
       discriminacao prefix)`. Brittle against `discriminacao` edits but
       deterministic within a declaration.

    The id is always prefixed with `irpf-{grupo}{codigo}-` so that:
    - Holdings sharing a CNPJ but living in different IRPF buckets (e.g.,
      `acao` ITUB4 in 03.01 and JCP-receivable in 99.07) do NOT collide.
    - Across years, the same `(grupo, codigo, identifier)` yields the same
      id, so `merge_holdings` updates rather than duplicates.
    """
    bucket = f"{grupo}{codigo}"

    ticker = (item.get("codigoNegociacao") or "").strip().upper()
    if ticker:
        return f"irpf-{bucket}-tk-{ticker.lower()}"

    altcoin = (item.get("codigoAltcoin") or "").strip()
    if altcoin:
        return f"irpf-{bucket}-alt-{altcoin.lower()}"
    stable = (item.get("codigoStablecoin") or "").strip()
    if stable:
        return f"irpf-{bucket}-stb-{stable.lower()}"

    cnpj_digits = re.sub(r"\D", "", item.get("niEmpresa") or "")

    # True mutual fund holdings (group 07.*) — CNPJ uniquely identifies the
    # fund itself. Group 04.02 (Fundos sujeitos à tributação periódica) is
    # excluded here because users frequently file CDB/Tesouro/etc. with the
    # broker custodian CNPJ in 04.02, so multiple distinct securities share
    # one CNPJ — those need a discriminacao-derived suffix to disambiguate.
    if grupo == "07" and cnpj_digits:
        return f"irpf-{bucket}-cnpj-{cnpj_digits}"

    # Cash account. Combine CNPJ (issuer), bank coordinates and a short
    # discriminacao hash. The hash disambiguates multiple products that share
    # the same agência/conta (e.g. checking + a payment-account product
    # riding on the same account number with the same issuer CNPJ). It also
    # keeps the id stable across years as long as the user does not edit the
    # discriminacao text materially.
    if grupo == "06":
        banco = re.sub(r"\D", "", item.get("banco") or "")
        agencia = re.sub(r"\D", "", item.get("agencia") or "")
        conta = re.sub(r"\D", "", item.get("conta") or "")
        disc_hash = hashlib.blake2s(
            _norm_text(item.get("discriminacao")).encode("utf-8"),
            digest_size=3,
        ).hexdigest()
        if banco and conta:
            cnpj_part = cnpj_digits or "0"
            return f"irpf-{bucket}-acct-{cnpj_part}-{banco}-{agencia or '0'}-{conta}-{disc_hash}"
        if cnpj_digits:
            # Foreign or non-Brazilian bank with no banco code.
            return f"irpf-{bucket}-cnpj-{cnpj_digits}-{disc_hash}"

    # Pension (99.06): plan provider CNPJ + product hash from discriminacao
    if grupo == "99" and codigo == "06" and cnpj_digits:
        disc_hash = hashlib.blake2s(
            _norm_text(item.get("discriminacao")).encode("utf-8"),
            digest_size=4,
        ).hexdigest()
        return f"irpf-{bucket}-cnpj-{cnpj_digits}-{disc_hash}"

    # Fallback: deterministic content hash. Used for real-estate, vehicles,
    # private equity, broker-held fixed income (04.03), and JCP receivables
    # where the asset has no structured key. Brittle against discriminacao
    # edits — flag this in metadata so users know.
    norm_disc = _norm_text(item.get("discriminacao"))
    fingerprint = f"{grupo}|{codigo}|{cnpj_digits}|{norm_disc}".encode("utf-8")
    digest = hashlib.blake2s(fingerprint, digest_size=8).hexdigest()
    return f"irpf-{bucket}-h-{digest}"


def _shorten_label(text: str, *, limit: int = 80) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def _identifiers(item: ET.Element) -> dict:
    ids: dict = {}
    ticker = (item.get("codigoNegociacao") or "").strip()
    if ticker:
        ids["ticker"] = ticker
    cnpj = _parse_cnpj(item.get("niEmpresa"))
    if cnpj:
        ids["cnpj"] = cnpj
    altcoin = (item.get("codigoAltcoin") or "").strip()
    if altcoin:
        ids["altcoin_code"] = altcoin
    stable = (item.get("codigoStablecoin") or "").strip()
    if stable:
        ids["stablecoin_code"] = stable
    return ids


def _account_metadata(item: ET.Element) -> dict | None:
    banco = (item.get("banco") or "").strip()
    agencia = (item.get("agencia") or "").strip()
    conta = (item.get("conta") or "").strip()
    dv = (item.get("dvConta") or "").strip()
    if not (banco or agencia or conta):
        return None
    info: dict = {}
    if banco:
        info["bank_code"] = banco
    if agencia:
        info["branch"] = agencia
    if conta:
        info["account_number"] = f"{conta}-{dv}" if dv else conta
    return info


def _build_holding(item: ET.Element, *, exercicio: int) -> dict | None:
    grupo = (item.get("grupo") or "").strip()
    codigo = (item.get("codigo") or "").strip()
    discriminacao = (item.get("discriminacao") or "").strip()
    ticker = (item.get("codigoNegociacao") or "").strip()
    indice = (item.get("indice") or "").strip()

    valor_atual = _parse_brl(item.get("valorExercicioAtual"))
    valor_anterior = _parse_brl(item.get("valorExercicioAnterior"))

    # Skip placeholder rows entirely empty in both years.
    if valor_atual == 0.0 and valor_anterior == 0.0 and not discriminacao:
        return None

    asset_type_id = _classify(grupo, codigo, discriminacao, ticker)

    holding: dict = {
        "id": _stable_holding_id(item, grupo=grupo, codigo=codigo),
        "asset_type_id": asset_type_id,
        "label": _shorten_label(discriminacao) or f"IRPF {grupo}/{codigo} #{indice}",
        "market_value": {
            "amount": round(valor_atual, 2),
            "currency": "BRL",
        },
    }

    identifiers = _identifiers(item)
    if identifiers:
        holding["identifiers"] = identifiers

    pais = (item.get("pais") or "").strip()
    nome_pais = (item.get("nomePais") or "").strip()
    if pais and pais != _IRPF_BRAZIL_CODE:
        # Foreign asset; jurisdiction.country needs ISO alpha-2 but IRPF only
        # gives a numeric code, so we keep the raw code in metadata only.
        pass
    if pais == _IRPF_BRAZIL_CODE:
        holding["jurisdiction"] = {"country": "BR"}

    metadata: dict = {
        "irpf": {
            "exercicio": exercicio,
            "grupo": grupo,
            "codigo": codigo,
            "indice": indice,
            "discriminacao": discriminacao,
        },
        "value_current_year_end": {"amount": round(valor_atual, 2), "currency": "BRL"},
        "value_prior_year_end": {"amount": round(valor_anterior, 2), "currency": "BRL"},
    }

    if nome_pais:
        metadata["irpf"]["country_label"] = nome_pais
    if pais:
        metadata["irpf"]["country_code"] = pais

    negociado_bolsa = (item.get("negociadoBolsa") or "").strip()
    if negociado_bolsa:
        metadata["irpf"]["negociado_bolsa"] = negociado_bolsa

    auto_custodiante = (item.get("indicadorAutoCustodiante") or "").strip()
    if auto_custodiante:
        metadata["irpf"]["auto_custodiante"] = auto_custodiante

    account = _account_metadata(item)
    if account:
        metadata["account"] = account

    metadata["irpf"]["id_strategy"] = _id_strategy(holding["id"])
    holding["metadata"] = metadata
    return holding


def _id_strategy(holding_id: str) -> str:
    """Reverse-look the id-derivation tag baked into the id.

    `irpf-<grupo><codigo>-<tag>-...` where tag is one of:
    `tk`, `alt`, `stb`, `cnpj`, `acct`, `h` (fallback hash).
    """
    parts = holding_id.split("-", 3)
    if len(parts) >= 3 and parts[0] == "irpf":
        return {
            "tk": "ticker",
            "alt": "altcoin_code",
            "stb": "stablecoin_code",
            "cnpj": "issuer_cnpj",
            "acct": "bank_account",
            "h": "discriminacao_hash",
        }.get(parts[2], "unknown")
    return "unknown"


def parse_statement(path: Path) -> dict:
    tree = ET.parse(path)
    root = tree.getroot()

    save_iso, exercicio = _parse_savedate(root.get("dataHoraSalvamento"))

    bens = root.find(f"{NS}bens")
    items = list(bens.findall(f"{NS}item")) if bens is not None else []

    holdings: list[dict] = []
    for it in items:
        h = _build_holding(it, exercicio=exercicio)
        if h is not None:
            holdings.append(h)

    payload: dict = {
        "provider": "irpf-xml",
        "generated_at": save_iso,
        "base_currency": "BRL",
        "holdings": holdings,
        "metadata": {
            "irpf_exercicio": exercicio,
            "current_year_end": f"{exercicio - 1}-12-31",
            "prior_year_end": f"{exercicio - 2}-12-31",
            "source_file": path.name,
        },
    }
    return payload


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: importer.py <declaration.xml>", file=sys.stderr)
        return 1
    payload = parse_statement(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
