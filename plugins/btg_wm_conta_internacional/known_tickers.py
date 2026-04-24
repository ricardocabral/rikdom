"""Static US ticker -> enrichment hints.

Brokers (including DriveWealth/BTG-US) bucket every listed security as
'Equity' regardless of what it economically is. A bond ETF, a gold ETF,
or a US REIT ETF will all arrive as 'stock' unless we look-through to
what the wrapper actually holds.

This module is a deterministic, offline-curated table. It is the ONLY
source of look-through knowledge for the BTG WM Conta Internacional
importer. To add a ticker: verify the issuer factsheet, then append an
entry. Do not guess. The `as_of` date documents when the classification
was last verified so agents can surface staleness.

Schema of each entry matches portfolio.schema.json $defs.EconomicExposure.
The optional `asset_type_id` key overrides the default bucket-based typing
(e.g., force SGOV and BND to `debt_instrument` instead of `stock`).
"""

from __future__ import annotations

from typing import Any

_AS_OF = "2026-04-01"


def _exposure(breakdown: list[dict[str, Any]], *, confidence: str = "high", notes: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "classification_source": "issuer_prospectus",
        "as_of": _AS_OF,
        "confidence": confidence,
        "breakdown": breakdown,
    }
    if notes:
        block["notes"] = notes
    return block


TICKER_HINTS: dict[str, dict[str, Any]] = {
    "VOO": {
        "economic_exposure": _exposure([
            {
                "weight_pct": 100,
                "asset_class": "stocks",
                "region": "US",
                "currency": "USD",
                "factor": "broad_market",
                "liquidity_tier": "t1",
            },
        ]),
    },
    "ACWI": {
        "economic_exposure": _exposure(
            [
                {"weight_pct": 62, "asset_class": "stocks", "region": "US", "currency": "USD", "factor": "broad_market", "liquidity_tier": "t1"},
                {"weight_pct": 27, "asset_class": "stocks", "region": "ex_US_DM", "currency": "USD", "factor": "broad_market", "liquidity_tier": "t1"},
                {"weight_pct": 11, "asset_class": "stocks", "region": "EM", "currency": "USD", "factor": "broad_market", "liquidity_tier": "t1"},
            ],
            notes="Approximate MSCI ACWI regional split; refresh periodically.",
        ),
    },
    "BND": {
        "asset_type_id": "debt_instrument",
        "economic_exposure": _exposure(
            [
                {
                    "weight_pct": 100,
                    "asset_class": "debt",
                    "region": "US",
                    "currency": "USD",
                    "duration": "intermediate",
                    "factor": "aggregate_bond",
                    "liquidity_tier": "t1",
                },
            ],
            notes="Vanguard Total Bond Market. Broker files as stock; economically US investment-grade aggregate debt.",
        ),
    },
    "SCHP": {
        "asset_type_id": "debt_instrument",
        "economic_exposure": _exposure(
            [
                {
                    "weight_pct": 100,
                    "asset_class": "debt",
                    "region": "US",
                    "currency": "USD",
                    "duration": "intermediate",
                    "factor": "sovereign_inflation_linked",
                    "liquidity_tier": "t1",
                },
            ],
            notes="Schwab US TIPS ETF. Economically US Treasury inflation-protected debt.",
        ),
    },
    "SGOV": {
        "asset_type_id": "cash_equivalent",
        "economic_exposure": _exposure(
            [
                {
                    "weight_pct": 100,
                    "asset_class": "cash_equivalents",
                    "region": "US",
                    "currency": "USD",
                    "duration": "cash",
                    "factor": "sovereign_floating",
                    "liquidity_tier": "t0",
                },
            ],
            notes="iShares 0-3 Month Treasury. Economically US T-bills, cash-like.",
        ),
    },
    "SCHH": {
        "economic_exposure": _exposure(
            [
                {
                    "weight_pct": 100,
                    "asset_class": "reits",
                    "region": "US",
                    "currency": "USD",
                    "sector": "real_estate",
                    "liquidity_tier": "t1",
                },
            ],
            notes="Schwab US REIT ETF. Economically US listed real estate.",
        ),
    },
    "GLD": {
        "economic_exposure": _exposure(
            [
                {
                    "weight_pct": 100,
                    "asset_class": "commodities",
                    "region": "GLOBAL",
                    "currency": "USD",
                    "sector": "precious_metals",
                    "liquidity_tier": "t1",
                },
            ],
            notes="SPDR Gold Shares. Physically-backed gold.",
        ),
    },
    "DWBDS": {
        "economic_exposure": _exposure(
            [
                {
                    "weight_pct": 100,
                    "asset_class": "cash_equivalents",
                    "region": "US",
                    "currency": "USD",
                    "duration": "cash",
                    "liquidity_tier": "t0",
                },
            ],
            confidence="high",
            notes="DriveWealth Bank Sweep (FDIC-insured deposit).",
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
