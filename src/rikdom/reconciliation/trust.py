from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FxSource = Literal[
    "identity",
    "fx_rates_to_base",
    "metadata.fx_rate_to_base",
]

ExcludedReason = Literal[
    "fx_missing",
    "invalid_money",
    "missing_market_value",
]


@dataclass(frozen=True)
class HoldingTrustRecord:
    """Per-holding trace of how a base-currency amount was derived.

    Captured during aggregation so reports can reproduce ``total_value_base``
    from raw inputs without re-running the pipeline.
    """

    holding_id: str
    asset_type_id: str
    asset_class: str
    source_amount: float | None
    source_currency: str | None
    base_currency: str
    base_amount: float | None
    fx_rate: float | None
    fx_source: FxSource | None
    fx_timestamp: str | None = None
    excluded_reason: ExcludedReason | None = None
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "holding_id": self.holding_id,
            "asset_type_id": self.asset_type_id,
            "asset_class": self.asset_class,
            "base_currency": self.base_currency,
        }
        if self.source_amount is not None:
            out["source_amount"] = self.source_amount
        if self.source_currency is not None:
            out["source_currency"] = self.source_currency
        if self.base_amount is not None:
            out["base_amount"] = self.base_amount
        if self.fx_rate is not None:
            out["fx_rate"] = self.fx_rate
        if self.fx_source is not None:
            out["fx_source"] = self.fx_source
        if self.fx_timestamp is not None:
            out["fx_timestamp"] = self.fx_timestamp
        if self.excluded_reason is not None:
            out["excluded_reason"] = self.excluded_reason
        if self.findings:
            out["findings"] = list(self.findings)
        return out
