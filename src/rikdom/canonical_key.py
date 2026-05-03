"""Cross-importer canonical keys for collapsing duplicate holdings.

A canonical key is a stable, importer-agnostic identifier for the underlying
asset behind a holding (e.g. ``br:acao:bbdc4``, ``br:fund:30934757000113``,
``us:stock:vti``). Two holdings minted by different importers for the same
asset should produce the same canonical key.

The merge pass uses canonical keys as a *fallback* dedup signal — only when
``--collapse-canonical`` is set on ``import-statement``. Existing portfolios
that lack canonical keys keep working unchanged.
"""

from __future__ import annotations

import re
from typing import Any


# Asset types that, in this repo's taxonomy, are exchange-listed securities
# whose ticker is the most stable cross-importer identifier.
_TICKER_KINDS_BR = {"acao", "fii", "etf", "bdr"}
_TICKER_KINDS_US = {"stock", "etf", "fund"}

_CNPJ_DIGIT_RE = re.compile(r"\D+")


def _clean_cnpj(raw: Any) -> str | None:
    if not raw:
        return None
    digits = _CNPJ_DIGIT_RE.sub("", str(raw))
    if len(digits) != 14 or digits == "0" * 14:
        return None
    return digits


def _clean_ticker(raw: Any) -> str | None:
    if not raw:
        return None
    text = str(raw).strip().lower()
    return text or None


def _country_code(raw: Any) -> str | None:
    if not raw:
        return None
    text = str(raw).strip().lower()
    if not re.fullmatch(r"[a-z]{2}", text):
        return None
    return text


def derive_canonical_key(holding: dict[str, Any]) -> str | None:
    """Mint a canonical key for a holding from its existing fields.

    Returns ``None`` when there is no stable cross-importer identifier
    (e.g. opaque labels, free-text-only positions). The caller should
    leave ``metadata.canonical_key`` unset in that case.
    """
    if not isinstance(holding, dict):
        return None

    asset_type = str(holding.get("asset_type_id") or "").strip().lower()
    identifiers = holding.get("identifiers") or {}
    if not isinstance(identifiers, dict):
        identifiers = {}
    jurisdiction = holding.get("jurisdiction") or {}
    if not isinstance(jurisdiction, dict):
        jurisdiction = {}

    country = _country_code(jurisdiction.get("country"))
    ticker = _clean_ticker(identifiers.get("ticker"))
    cnpj = _clean_cnpj(identifiers.get("cnpj"))

    # Brazilian exchange-listed security types — ticker is the canonical id.
    if asset_type in _TICKER_KINDS_BR and ticker and ticker != "cash":
        return f"br:{asset_type}:{ticker}"

    # Brazilian funds and pension products — issuer CNPJ is canonical.
    _BR_FUND_KINDS = {
        "fund",
        "fundo_investimento",
        "fundo_imobiliario_fechado",
        "fundo_multimercado",
        "fundo_renda_fixa",
        "fundo_acoes",
    }
    if asset_type in _BR_FUND_KINDS and cnpj:
        return f"br:fund:{cnpj}"
    if asset_type in {"previdencia_privada", "previdencia"} and cnpj:
        return f"br:previdencia:{cnpj}"

    # Crypto — altcoin/stablecoin codes are canonical regardless of venue.
    altcoin = _clean_ticker(identifiers.get("altcoin_code"))
    if altcoin:
        return f"crypto:altcoin:{altcoin}"
    stablecoin = _clean_ticker(identifiers.get("stablecoin_code"))
    if stablecoin:
        return f"crypto:stablecoin:{stablecoin}"

    # Cash — currency uniquely identifies the asset.
    if asset_type == "cash_equivalent":
        currency = holding.get("market_value") or {}
        if isinstance(currency, dict):
            cur = str(currency.get("currency") or "").strip().lower()
            if re.fullmatch(r"[a-z]{3}", cur):
                return f"cash:{cur}"

    # Foreign-listed equities/funds — country + ticker. Default region is
    # ``us`` since most non-BR brokerages in this repo (Schwab, Fidelity,
    # Vanguard, IBKR, etc.) hold US-listed names.
    if ticker and asset_type in _TICKER_KINDS_US:
        region = country or "us"
        if region == "br":
            # If country says BR but asset_type is generic "stock"/"etf"/"fund",
            # treat it as a BR equity — most likely an ADR/foreign mapping that
            # routes back to a BR ticker.
            return f"br:{asset_type}:{ticker}"
        return f"{region}:{asset_type}:{ticker}"

    return None


def assign_canonical_keys(payload: dict[str, Any]) -> int:
    """Inject ``metadata.canonical_key`` on every holding in ``payload``.

    Idempotent: if a holding already declares ``metadata.canonical_key`` the
    importer's value wins. Returns the number of holdings the helper actually
    populated.
    """
    holdings = payload.get("holdings")
    if not isinstance(holdings, list):
        return 0

    populated = 0
    for entry in holdings:
        if not isinstance(entry, dict):
            continue
        meta = entry.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
            entry["metadata"] = meta
        if meta.get("canonical_key"):
            continue
        key = derive_canonical_key(entry)
        if key:
            meta["canonical_key"] = key
            populated += 1
    return populated


def holding_canonical_key(holding: dict[str, Any]) -> str | None:
    """Read a stored canonical key, preferring the explicit metadata field."""
    if not isinstance(holding, dict):
        return None
    meta = holding.get("metadata")
    if isinstance(meta, dict):
        key = meta.get("canonical_key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    return None
