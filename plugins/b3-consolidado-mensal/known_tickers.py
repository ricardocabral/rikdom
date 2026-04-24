"""Static BR ticker -> enrichment hints for the B3 consolidated importer.

The B3 monthly consolidated report lists every holding in generic sheets
(Acoes, ETF, Fundos, Tesouro Direto, Renda Fixa) with minimal metadata.
FIIs and FIAGROs land on the 'Fundos' sheet and lack the `fund_cnpj`,
`fii_type`, `segment` fields that the asset-types-br-catalog's strict
types require. ETFs land on the ETF sheet as a generic `fund` even when
we already have specialised catalog types with correct economic_exposure.

This table fills the gap deterministically, without network calls. To
add a ticker: verify its asset type, CNPJ (when known), and economic
exposure from B3/CVM public data, then append an entry.

For FIIs/FIAGROs where we don't have a verified fund_cnpj we ship only
`economic_exposure` so agents see correct risk classification; the
holding stays tagged as the generic `fund` type to avoid triggering
strict instrument_attribute validation.
"""

from __future__ import annotations

from typing import Any

_AS_OF = "2026-04-01"


def _exposure(breakdown: list[dict[str, Any]], *, confidence: str = "high", notes: str | None = None, source: str = "issuer_prospectus") -> dict[str, Any]:
    block: dict[str, Any] = {
        "classification_source": source,
        "as_of": _AS_OF,
        "confidence": confidence,
        "breakdown": breakdown,
    }
    if notes:
        block["notes"] = notes
    return block


_ETF_UNDERLYING: dict[str, str] = {
    "BOVA11": "RENDA_VARIAVEL",
    "IVVB11": "INTERNACIONAL",
    "SMAL11": "RENDA_VARIAVEL",
    "DIVO11": "RENDA_VARIAVEL",
    "FIXA11": "RENDA_FIXA",
    "IMAB11": "RENDA_FIXA",
    "B5P211": "RENDA_FIXA",
    "GOLD11": "COMMODITIES",
    "HASH11": "CRIPTO",
    "ACWI11": "INTERNACIONAL",
    "XINA11": "INTERNACIONAL",
    "XFIX11": "RENDA_VARIAVEL",
}


def _etf_hint(ticker: str) -> dict[str, Any]:
    return {
        "asset_type_id": f"etf_{ticker.lower()}",
        "instrument_attributes": {
            "b3_ticker": ticker,
            "underlying_class": _ETF_UNDERLYING[ticker],
            "tax_profile.ir_pf_treatment": "ALIQUOTA_FIXA",
        },
    }


TICKER_HINTS: dict[str, dict[str, Any]] = {
    # --- ETFs with specialised catalog types (retag + required instrument_attributes) ---
    **{t: _etf_hint(t) for t in _ETF_UNDERLYING},

    # --- FIIs (no verified CNPJ; ship exposure only so holdings stay as 'fund') ---
    "HSLG11": {
        "economic_exposure": _exposure(
            [{"weight_pct": 100, "asset_class": "reits", "region": "BR", "currency": "BRL", "sector": "logistics", "liquidity_tier": "t1"}],
            source="manual",
            notes="HSI Logística FII (tijolo logístico).",
        ),
    },
    "RBRY11": {
        "economic_exposure": _exposure(
            [{"weight_pct": 100, "asset_class": "debt", "region": "BR", "currency": "BRL", "duration": "intermediate", "factor": "securitised_real_estate", "liquidity_tier": "t1"}],
            source="manual",
            notes="Patria Crédito Imobiliário Estruturado (FII de papel/CRIs).",
        ),
    },

    # --- FIAGROs (biased to FIDC_LIKE / receivables) ---
    "RURA11": {
        "economic_exposure": _exposure(
            [{"weight_pct": 100, "asset_class": "debt", "region": "BR", "currency": "BRL", "duration": "intermediate", "sector": "agribusiness", "factor": "securitised_agribusiness", "liquidity_tier": "t1"}],
            source="manual",
            confidence="medium",
            notes="Itau Asset Rural FIAGRO Imobiliário (CRAs).",
        ),
    },
    "VGIA11": {
        "economic_exposure": _exposure(
            [{"weight_pct": 100, "asset_class": "debt", "region": "BR", "currency": "BRL", "duration": "intermediate", "sector": "agribusiness", "factor": "securitised_agribusiness", "liquidity_tier": "t1"}],
            source="manual",
            notes="Valora CRA FIAGRO.",
        ),
    },
}


def enrich_holding(holding: dict[str, Any]) -> None:
    """Apply ticker-level hints in place. No-op when ticker is unknown."""
    ticker = (holding.get("identifiers") or {}).get("ticker")
    if not ticker:
        return
    hint = TICKER_HINTS.get(ticker.upper())
    if not hint:
        return
    if "asset_type_id" in hint:
        holding["asset_type_id"] = hint["asset_type_id"]
    if "economic_exposure" in hint:
        holding["economic_exposure"] = hint["economic_exposure"]
    extra_attrs = hint.get("instrument_attributes")
    if extra_attrs:
        attrs = holding.setdefault("instrument_attributes", {})
        for k, v in extra_attrs.items():
            attrs.setdefault(k, v)
