from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rikdom.reconciliation.codes import Severity

if TYPE_CHECKING:
    from rikdom.aggregate import AggregateResult


HOLDING_TRUST_SCHEMA_URI = (
    "https://rikdom.dev/schemas/reports/holding_trust/v1.json"
)
RECONCILIATION_SCHEMA_URI = (
    "https://rikdom.dev/schemas/reports/reconciliation/v1.json"
)
SCHEMA_VERSION = "1.0.0"

_INVARIANT_TOLERANCE = 0.01


def render_holding_trust_json(
    result: "AggregateResult",
    *,
    portfolio_id: str,
    generated_at: str,
) -> dict[str, Any]:
    holdings = [r.to_dict() for r in result.trust_records]
    sum_holdings_base = round(
        sum(
            r.base_amount or 0.0
            for r in result.trust_records
            if r.excluded_reason is None
        ),
        2,
    )
    excluded = [
        r.holding_id for r in result.trust_records if r.excluded_reason is not None
    ]
    return {
        "schema_uri": HOLDING_TRUST_SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "portfolio_id": portfolio_id,
        "base_currency": result.base_currency,
        "total_value_base": result.total_value_base,
        "holdings": holdings,
        "invariant": {
            "sum_holdings_base": sum_holdings_base,
            "total_value_base": result.total_value_base,
            "matches": abs(sum_holdings_base - result.total_value_base)
            <= _INVARIANT_TOLERANCE,
            "excluded_holding_ids": excluded,
        },
    }


def render_holding_trust_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Holding Trust Report — {report['portfolio_id']}")
    lines.append("")
    lines.append(f"- Generated: {report['generated_at']}")
    lines.append(f"- Base currency: `{report['base_currency']}`")
    lines.append(f"- Total value (base): `{report['total_value_base']}`")
    lines.append("")
    lines.append(
        "| Holding | Asset class | Source amount | Source ccy | FX rate | FX source | Base amount | Excluded | Findings |"
    )
    lines.append(
        "| --- | --- | ---: | --- | ---: | --- | ---: | --- | --- |"
    )
    for h in report["holdings"]:
        excluded = h.get("excluded_reason", "")
        findings = ", ".join(h.get("findings", [])) or ""
        lines.append(
            "| `{hid}` | {ac} | {sa} | {sc} | {fr} | {fs} | {ba} | {ex} | {fd} |".format(
                hid=h.get("holding_id", ""),
                ac=h.get("asset_class", ""),
                sa=h.get("source_amount", ""),
                sc=h.get("source_currency", ""),
                fr=h.get("fx_rate", ""),
                fs=h.get("fx_source", ""),
                ba=h.get("base_amount", ""),
                ex=excluded,
                fd=findings,
            )
        )
    inv = report["invariant"]
    lines.append("")
    lines.append("## Invariant")
    lines.append("")
    lines.append(f"- Sum of holding base amounts: `{inv['sum_holdings_base']}`")
    lines.append(f"- Reported total value (base): `{inv['total_value_base']}`")
    status = "PASS" if inv["matches"] else "FAIL"
    lines.append(f"- Match: **{status}**")
    if inv["excluded_holding_ids"]:
        ids = ", ".join(f"`{i}`" for i in inv["excluded_holding_ids"])
        lines.append(f"- Excluded from total: {ids}")
    lines.append("")
    return "\n".join(lines)


def render_reconciliation_json(
    result: "AggregateResult",
    *,
    portfolio_id: str,
    generated_at: str,
) -> dict[str, Any]:
    by_severity: dict[str, int] = {"info": 0, "warning": 0, "error": 0}
    by_code: dict[str, int] = {}
    for f in result.findings:
        by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1
        by_code[f.code] = by_code.get(f.code, 0) + 1

    return {
        "schema_uri": RECONCILIATION_SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "portfolio_id": portfolio_id,
        "summary": {
            "total": len(result.findings),
            "error_count": by_severity["error"],
            "warning_count": by_severity["warning"],
            "info_count": by_severity["info"],
            "by_code": dict(sorted(by_code.items())),
        },
        "findings": [f.to_dict() for f in result.findings],
    }


_SEVERITY_ORDER = (Severity.ERROR, Severity.WARNING, Severity.INFO)


def render_reconciliation_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Reconciliation Report — {report['portfolio_id']}")
    lines.append("")
    lines.append(f"- Generated: {report['generated_at']}")
    summary = report["summary"]
    lines.append(
        f"- Findings: **{summary['total']}** "
        f"(errors: {summary['error_count']}, "
        f"warnings: {summary['warning_count']}, "
        f"info: {summary['info_count']})"
    )
    if summary["by_code"]:
        lines.append("")
        lines.append("## By code")
        lines.append("")
        lines.append("| Code | Count |")
        lines.append("| --- | ---: |")
        for code, count in summary["by_code"].items():
            lines.append(f"| `{code}` | {count} |")

    grouped: dict[str, list[dict[str, Any]]] = {"error": [], "warning": [], "info": []}
    for f in report["findings"]:
        grouped.setdefault(f["severity"], []).append(f)

    for severity in ("error", "warning", "info"):
        bucket = grouped.get(severity, [])
        if not bucket:
            continue
        lines.append("")
        lines.append(f"## {severity.title()} ({len(bucket)})")
        lines.append("")
        for f in bucket:
            lines.append(f"### `{f['code']}` — {f.get('scope', '')}")
            lines.append("")
            lines.append(f"- Message: {f['message']}")
            if f.get("refs"):
                refs_str = ", ".join(f"`{k}={v}`" for k, v in f["refs"].items())
                lines.append(f"- Refs: {refs_str}")
            if f.get("observed") is not None:
                lines.append(f"- Observed: `{f['observed']}`")
            if f.get("expected") is not None:
                lines.append(f"- Expected: `{f['expected']}`")
            if f.get("suggested_fix"):
                lines.append(f"- Suggested fix: {f['suggested_fix']}")
            lines.append("")
    return "\n".join(lines)
