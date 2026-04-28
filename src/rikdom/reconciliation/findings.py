from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from rikdom.reconciliation.codes import Severity, default_severity


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    scope: str = ""
    refs: dict[str, str] = field(default_factory=dict)
    observed: Any = None
    expected: Any = None
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.scope:
            out["scope"] = self.scope
        if self.refs:
            out["refs"] = dict(self.refs)
        if self.observed is not None:
            out["observed"] = deepcopy(self.observed)
        if self.expected is not None:
            out["expected"] = deepcopy(self.expected)
        if self.suggested_fix:
            out["suggested_fix"] = self.suggested_fix
        return out


def record_finding(
    findings: list[Finding] | None,
    code: str,
    message: str,
    *,
    severity: Severity | None = None,
    scope: str = "",
    refs: dict[str, str] | None = None,
    observed: Any = None,
    expected: Any = None,
    suggested_fix: str = "",
) -> None:
    """Append a structured Finding to ``findings`` if it is not None.

    Callers continue to append the human-readable string to their existing
    ``warnings`` list separately; this helper only handles the structured
    sibling artifact.
    """

    if findings is None:
        return
    findings.append(
        Finding(
            code=code,
            severity=severity or default_severity(code),
            message=message,
            scope=scope,
            refs=dict(refs) if refs else {},
            observed=deepcopy(observed),
            expected=deepcopy(expected),
            suggested_fix=suggested_fix,
        )
    )
