from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Mapping


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# Stable issue codes for reconciliation findings and trust diagnostics.
# Codes are part of the public reporting contract; do not rename without a
# deprecation cycle. New codes append to this registry.
_REGISTRY: dict[str, Severity] = {
    # FX / trust
    "RECON_FX_MISSING": Severity.WARNING,
    "TRUST_FX_FALLBACK_USED": Severity.WARNING,
    # Money shape
    "RECON_INVALID_MONEY": Severity.WARNING,
    # Holdings
    "RECON_MALFORMED_HOLDING": Severity.WARNING,
    "RECON_LOOKTHROUGH_NON_POSITIVE_WEIGHT": Severity.WARNING,
    # Activity-to-holding reconciliation
    "RECON_QTY_LEDGER_MISMATCH": Severity.WARNING,
    "RECON_CASH_DRIFT": Severity.WARNING,
}

ISSUE_CODES: Mapping[str, Severity] = MappingProxyType(_REGISTRY)


def default_severity(code: str) -> Severity:
    try:
        return ISSUE_CODES[code]
    except KeyError as exc:
        raise ValueError(f"Unknown reconciliation code: {code!r}") from exc
