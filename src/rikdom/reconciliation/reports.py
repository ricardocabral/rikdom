from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rikdom.storage import save_json
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
    fx_context = copy.deepcopy(result.fx_lock or {})
    rates = fx_context.get("rates_to_base")
    rates = rates if isinstance(rates, dict) else {}
    dates = fx_context.get("rate_dates")
    dates = dates if isinstance(dates, dict) else {}
    sources = fx_context.get("sources")
    sources = sources if isinstance(sources, dict) else {}
    for holding in holdings:
        currency = holding.get("source_currency")
        if (
            holding.get("fx_source") == "fx_rates_to_base"
            and rates.get(currency) == holding.get("fx_rate")
            and fx_context.get("base_currency", result.base_currency) == result.base_currency
        ):
            effective = dates.get(currency)
            if isinstance(effective, str) and len(effective) == 10:
                try:
                    if date.fromisoformat(effective).isoformat() == effective:
                        holding["fx_timestamp"] = effective
                except ValueError:
                    pass
            provider = sources.get(currency)
            if isinstance(provider, str) and provider:
                holding["fx_provider"] = provider
    sum_holdings_base = sum(
            r.base_amount or 0.0
            for r in result.trust_records
            if r.excluded_reason is None
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
        "fx_context": fx_context,
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
        "| Holding | Asset class | Source amount | Source ccy | FX rate | FX source | FX effective date | FX provider | Base amount | Excluded | Findings |"
    )
    lines.append(
        "| --- | --- | ---: | --- | ---: | --- | --- | --- | ---: | --- | --- |"
    )
    for h in report["holdings"]:
        excluded = h.get("excluded_reason", "")
        findings = ", ".join(h.get("findings", [])) or ""
        lines.append(
            "| `{hid}` | {ac} | {sa} | {sc} | {fr} | {fs} | {ft} | {fp} | {ba} | {ex} | {fd} |".format(
                hid=h.get("holding_id", ""),
                ac=h.get("asset_class", ""),
                sa=h.get("source_amount", ""),
                sc=h.get("source_currency", ""),
                fr=h.get("fx_rate", ""),
                fs=h.get("fx_source", ""),
                ft=h.get("fx_timestamp", "unknown"),
                fp=h.get("fx_provider", ""),
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

    diagnostics = copy.deepcopy(getattr(result, "import_diagnostics", {}) or {})
    coverage = diagnostics.get("history_coverage", [])
    by_coverage_status = {"complete": 0, "partial": 0, "unknown": 0}
    for entry in coverage:
        status = entry.get("status", "unknown")
        by_coverage_status[status] = by_coverage_status.get(status, 0) + 1
    quantity = copy.deepcopy(getattr(result, "quantity_reconciliation", []) or [])
    quantity_summary = {"matched": 0, "mismatched": 0, "not_computable": 0}
    for entry in quantity:
        status = entry.get("status", "not_computable")
        quantity_summary[status] = quantity_summary.get(status, 0) + 1

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
        "warnings": list(result.warnings),
        "import_diagnostics": diagnostics,
        "coverage_summary": {
            "status": "declared" if coverage else "unknown",
            "declaration_count": len(coverage),
            "by_status": by_coverage_status,
            "unsupported_event_count": len(diagnostics.get("unsupported_events", [])),
            "note": "Coverage applies only to declared scopes and periods; zero findings do not prove complete history.",
        },
        "quantity_summary": quantity_summary,
        "quantity_reconciliation": quantity,
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
    coverage = report.get("coverage_summary", {"status": "unknown", "by_status": {}})
    quantity = report.get("quantity_summary", {})
    lines.extend([
        "", "## Coverage and quantity", "",
        f"- History coverage: **{coverage['status']}** (declared periods only)",
        f"- Coverage declarations: `{coverage.get('by_status', {})}`",
        f"- Unsupported events: `{coverage.get('unsupported_event_count', 0)}`",
        f"- Quantity matched: `{quantity.get('matched', 0)}`; mismatched: `{quantity.get('mismatched', 0)}`; not computable: `{quantity.get('not_computable', 0)}`",
        "- Zero findings do not prove complete history.",
    ])
    for entry in report.get("quantity_reconciliation", []):
        lines.append(f"- `{entry.get('holding_id', '')}`: {entry.get('status', 'not_computable')} — {entry.get('reason', ', '.join(entry.get('reasons', [])))}")
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
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


def build_trust_reports(
    result: "AggregateResult", *, portfolio_id: str, generated_at: str
) -> dict[str, dict[str, Any]]:
    """Build both existing trust payloads from one valuation, without acquisition."""
    return {
        "holding_trust": render_holding_trust_json(
            result, portfolio_id=portfolio_id, generated_at=generated_at
        ),
        "reconciliation": render_reconciliation_json(
            result, portfolio_id=portfolio_id, generated_at=generated_at
        ),
    }


def write_trust_reports(
    reports: dict[str, dict[str, Any]], output_dir: str | Path, *, format: str = "both"
) -> list[dict[str, str]]:
    """Write the existing JSON/Markdown formats and return their artifact paths."""
    if format not in {"both", "json", "md"}:
        raise ValueError("Trust report format must be both, json or md")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for extension in ("json", "md"):
        if format not in {"both", extension}:
            continue
        for name, renderer in (
            ("holding_trust", render_holding_trust_markdown),
            ("reconciliation", render_reconciliation_markdown),
        ):
            path = out_dir / f"{name}.{extension}"
            if extension == "json":
                save_json(str(path), reports[name])
            else:
                path.write_text(renderer(reports[name]), encoding="utf-8")
            artifacts.append({"type": f"{name}_{extension}", "path": str(path)})
    return artifacts
