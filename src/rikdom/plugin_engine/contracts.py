from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PhaseName:
    SOURCE_INPUT = "source/input"
    CONNECTOR = "external/connector"
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
        CONNECTOR,
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

