from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AggregateResult:
    base_currency: str
    total_value_base: float
    by_asset_class: dict[str, float]
    warnings: list[str]



def _asset_class_index(asset_type_catalog: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in asset_type_catalog:
        type_id = str(item.get("id", "")).strip()
        asset_class = str(item.get("asset_class", "other")).strip() or "other"
        if type_id:
            index[type_id] = asset_class
    return index


def _to_base_amount(holding: dict[str, Any], base_currency: str) -> float | None:
    market_value = holding.get("market_value")
    if not isinstance(market_value, dict):
        return None
    amount = market_value.get("amount")
    currency = market_value.get("currency")
    if not isinstance(amount, (int, float)):
        return None
    if currency == base_currency:
        return float(amount)

    metadata = holding.get("metadata")
    fx_rate = metadata.get("fx_rate_to_base") if isinstance(metadata, dict) else None
    if isinstance(fx_rate, (int, float)) and fx_rate > 0:
        return float(amount) * float(fx_rate)
    return None


def aggregate_portfolio(portfolio: dict[str, Any]) -> AggregateResult:
    settings = portfolio.get("settings", {})
    base_currency = settings.get("base_currency", "USD")

    catalog = portfolio.get("asset_type_catalog", [])
    holdings = portfolio.get("holdings", [])
    class_index = _asset_class_index(catalog if isinstance(catalog, list) else [])

    by_asset_class: dict[str, float] = {}
    warnings: list[str] = []

    for holding in holdings if isinstance(holdings, list) else []:
        if not isinstance(holding, dict):
            warnings.append("Skipped malformed holding entry")
            continue

        amount_base = _to_base_amount(holding, base_currency)
        if amount_base is None:
            hid = str(holding.get("id", "unknown"))
            warnings.append(
                f"Holding '{hid}' missing base conversion: add metadata.fx_rate_to_base"
            )
            continue

        asset_type_id = str(holding.get("asset_type_id", ""))
        asset_class = class_index.get(asset_type_id, "other")
        by_asset_class[asset_class] = by_asset_class.get(asset_class, 0.0) + amount_base

    total_value = sum(by_asset_class.values())
    return AggregateResult(
        base_currency=base_currency,
        total_value_base=round(total_value, 2),
        by_asset_class={k: round(v, 2) for k, v in sorted(by_asset_class.items())},
        warnings=warnings,
    )
