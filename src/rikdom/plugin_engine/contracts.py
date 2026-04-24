from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PhaseName:
    SOURCE_INPUT = "source/input"
    TRANSFORM = "transform"
    ENRICHMENT = "enrichment"
    STRATEGY_DECISION = "strategy/decision"
    EXECUTION = "execution"
    OUTPUT = "output"
    RISK_COMPLIANCE = "risk/compliance"
    STATE_STORAGE = "state/storage"
    ORCHESTRATION = "orchestration"
    OBSERVABILITY = "observability"
    AUTH_SECURITY = "auth/security"
    NOTIFICATION = "notification"
    SIMULATION_BACKTEST = "simulation/backtest"
    ASSET_TYPE_CATALOG = "asset-type/catalog"
    ALL = {
        SOURCE_INPUT,
        TRANSFORM,
        ENRICHMENT,
        STRATEGY_DECISION,
        EXECUTION,
        OUTPUT,
        RISK_COMPLIANCE,
        STATE_STORAGE,
        ORCHESTRATION,
        OBSERVABILITY,
        AUTH_SECURITY,
        NOTIFICATION,
        SIMULATION_BACKTEST,
        ASSET_TYPE_CATALOG,
    }


BRAZIL_CNPJ_REGEX = r"^\d{14}$"
BRAZIL_ISIN_REGEX = r"^BR[A-Z0-9]{9}\d$"
BRAZIL_B3_TICKER_REGEX = r"^[A-Z]{4}\d{2}[A-Z]?$"
BRAZIL_B3_ETF_TICKER_REGEX = r"^[A-Z0-9]{4}\d{2}[A-Z]?$"
BRAZIL_INDEXER_ENUM = ["CDI_DI_OVER", "IPCA", "SELIC", "PREFIXADO"]


@dataclass(slots=True)
class PluginContext:
    run_id: str
    plugin_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutputRequest:
    portfolio_path: str
    snapshots_path: str
    output_dir: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutputResult:
    plugin: str
    artifacts: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)

