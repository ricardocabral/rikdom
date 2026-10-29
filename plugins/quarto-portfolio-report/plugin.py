from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from rikdom.activities import effective_activities
from rikdom.aggregate import aggregate_portfolio
from rikdom.benchmarks import make_dir_loader
from rikdom.fx import ensure_snapshot_fx_lock
from rikdom.income import build_income_report
from rikdom.performance_report import performance_to_dict, recorded_contributions, load_performance_inputs
from rikdom.performance import (
    compute_performance, external_cashflow_currencies, performance_period_bounds,
)
from rikdom.plugin_engine.hookspecs import hookimpl
from rikdom.reconciliation.reports import build_trust_reports, write_trust_reports
from rikdom.storage import load_json, load_jsonl

QUARTO_TIMEOUT_SECONDS = 120
REPORT_FILENAME = "portfolio-report.html"
QUICKVIEW_FILENAME = "dashboard.html"


def _normalize_currency_code(value: Any, *, fallback: str = "UNKNOWN") -> str:
    code = str(value or "").strip().upper()
    if len(code) == 3 and code.isascii() and code.isalpha():
        return code
    return fallback


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            amount = float(text)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(amount):
        return None
    return amount


def _asset_type_bucket(asset_type_id: str, asset_class: str) -> str:
    if asset_type_id == "debt_instrument":
        return "debt_instrument"
    if asset_class == "debt":
        return "debt_instrument"
    return asset_type_id or "unknown"


def _latest_fx_lock(
    snapshots: list[dict[str, Any]],
    *,
    base_currency: str,
) -> dict[str, Any]:
    for snapshot in reversed(snapshots):
        if not isinstance(snapshot, dict):
            continue
        metadata = snapshot.get("metadata")
        if not isinstance(metadata, dict):
            continue
        fx_lock = metadata.get("fx_lock")
        if not isinstance(fx_lock, dict):
            continue
        lock_base = str(fx_lock.get("base_currency", "")).strip().upper()
        if lock_base and lock_base != base_currency:
            continue
        raw_rates = fx_lock.get("rates_to_base")
        if not isinstance(raw_rates, dict):
            continue

        normalized: dict[str, float] = {}
        for currency, rate in raw_rates.items():
            code = str(currency).strip().upper()
            parsed = _safe_float(rate)
            if not code or parsed is None or parsed <= 0:
                continue
            normalized[code] = parsed
        if normalized:
            lock = copy.deepcopy(fx_lock)
            lock["rates_to_base"] = normalized
            return lock

    return {}


def _build_quickview_currency_split(trust_records) -> dict[str, Any]:
    native: dict[str, float] = {}
    converted_base: dict[str, float] = {}
    missing_rates: set[str] = set()
    for record in trust_records:
        currency = _normalize_currency_code(record.source_currency)
        if record.source_amount is not None:
            native[currency] = native.get(currency, 0.0) + record.source_amount
        if record.excluded_reason == "fx_missing":
            missing_rates.add(currency)
        if record.excluded_reason is None and record.base_amount is not None:
            converted_base[currency] = converted_base.get(currency, 0.0) + record.base_amount
    return {
        "native": {k: round(v, 2) for k, v in sorted(native.items())},
        "converted_base": {
            k: round(v, 2) for k, v in sorted(converted_base.items(), key=lambda item: (-item[1], item[0]))
        },
        "missing_rates": sorted(missing_rates),
    }


def _extract_asset_class_targets(portfolio: dict[str, Any]) -> dict[str, float]:
    candidates: list[Any] = [
        portfolio.get("target_allocation_by_asset_class"),
        portfolio.get("settings", {}).get("target_allocation_by_asset_class")
        if isinstance(portfolio.get("settings"), dict)
        else None,
        portfolio.get("metadata", {}).get("target_allocation_by_asset_class")
        if isinstance(portfolio.get("metadata"), dict)
        else None,
    ]
    raw: dict[str, float] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key, value in candidate.items():
            parsed = _safe_float(value)
            if parsed is None or parsed < 0:
                continue
            raw[str(key)] = parsed
        if raw:
            break

    if not raw:
        return {}

    total = sum(raw.values())
    if total > 1.5:
        normalized = {k: v / 100.0 for k, v in raw.items()}
    else:
        normalized = raw

    norm_total = sum(normalized.values())
    if norm_total <= 0:
        return {}

    return {k: round(v / norm_total, 6) for k, v in normalized.items() if v > 0}


def _maturity_bucket(maturity_date: str | None, *, reference_date: datetime) -> str:
    if not maturity_date:
        return "unknown"
    try:
        maturity = datetime.fromisoformat(maturity_date.strip()).date()
    except ValueError:
        return "unknown"
    years = (maturity - reference_date.date()).days / 365.25
    if years <= 1:
        return "<=1y"
    if years <= 3:
        return "1-3y"
    if years <= 5:
        return "3-5y"
    return ">5y"


def _build_performance_section(
    portfolio: dict[str, Any], snapshots: list[dict[str, Any]], preferences: dict[str, Any],
    *, source_dir: Path, generated_at: str, overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resolve explicit local evidence and present the same result as the CLI.

    Failed evidence rejects this section, never the valuation/report as a whole.
    No current-valuation FX lock is substituted for historical return inputs.
    """
    context = {"status": "available", "scope": "portfolio", "inputs": {}, "warnings": [],
               "fees_and_taxes": "Embedded in snapshot values; not separately calculated. Income is embedded in valuations and is not added again."}
    try:
        options = preferences.get("performance", {})
        allowed = {"flow_valuations_path", "historical_fx_path", "fx_history_path", "policy_path", "benchmarks_dir", "since", "until", "historical_valuations_path", "profit_basis_path"}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError("rikdom_report.performance must contain only documented local input options")
        options = dict(options)
        aliases = {'flow_valuations':'flow_valuations_path', 'historical_fx':'historical_fx_path',
                   'historical_valuations':'historical_valuations_path', 'profit_basis':'profit_basis_path',
                   'fx_history':'fx_history_path', 'policy':'policy_path'}
        for name, value in (overrides or {}).items():
            key = aliases.get(name, name)
            if key not in allowed:
                raise ValueError(f'Unknown report calculation option: {name}')
            if key.endswith('_path') or key == 'benchmarks_dir':
                if not isinstance(value, str) or not value.strip() or '://' in value:
                    raise ValueError(f'{name} must be a local filesystem path')
                value = str(Path(value).resolve())
            options[key] = value

        def local_path(key: str, default: str | None = None) -> Path | None:
            raw = options.get(key, default)
            if raw is None and key not in options:
                return None
            if not isinstance(raw, str) or not raw.strip() or "://" in raw:
                raise ValueError(f"{key} must be a local filesystem path")
            path = Path(raw)
            if not path.is_absolute():
                path = source_dir / path
            if key in options:
                context["inputs"][key] = path.name
            return path

        base = str(portfolio.get("settings", {}).get("base_currency", "USD")).strip().upper() or "USD"
        paths = {}
        for name, key in (('flow_valuations','flow_valuations_path'), ('historical_fx','historical_fx_path'),
                          ('historical_valuations','historical_valuations_path'), ('profit_basis','profit_basis_path')):
            selected = local_path(key)
            if selected is not None:
                paths[name] = str(selected)
        inputs = load_performance_inputs(paths, base_currency=base)
        flow, historical = inputs['flow_valuations'], inputs['historical_fx']
        replay = inputs['valuation_replay']
        if replay is not None:
            snapshots = replay['snapshots']
        policy_path = local_path("policy_path")
        policy = load_json(str(policy_path)) if policy_path else None
        if policy_path is not None and not isinstance(policy, dict):
            raise ValueError("policy_path must contain a policy JSON object")
        benchmark_dir = local_path("benchmarks_dir", "benchmarks")
        activities = portfolio.get("activities") or []
        since, until = options.get("since"), options.get("until")
        for key, value in (("since", since), ("until", until)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{key} must be an ISO date or timestamp")
        context["requested_window"] = {"since": since, "until": until}
        lock, fx_warnings = {}, []
        if historical is None:
            start, end = performance_period_bounds(snapshots, since=since, until=until)
            lock, fx_warnings = ensure_snapshot_fx_lock(
                portfolio, fx_history_path=str(local_path("fx_history_path", "fx_rates.jsonl")),
                snapshot_timestamp=generated_at, auto_ingest=False,
                extra_quote_currencies=external_cashflow_currencies(
                    effective_activities(activities), base, period_start=start, period_end=end),
            )
        result = compute_performance(
            snapshots, activities, base_currency=base, fx_rates_to_base=lock.get("rates_to_base"),
            historical_fx=historical, since=since, until=until, policy=policy,
            benchmark_loader=make_dir_loader(benchmark_dir) if policy is not None else None,
            flow_valuations=flow,
        )
        result.warnings.extend(fx_warnings)
        if flow is not None:
            context["flow_valuations"] = flow
        return performance_to_dict(result, portfolio=portfolio, profit_basis=inputs['profit_basis'],
                                   historical_fx=historical, valuation_replay=replay), context
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        # OSError text contains absolute filenames; report only its explanation.
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        context.update(status="unavailable", warnings=[f"Performance unavailable: {detail}"])
        return None, context


def _build_report_payload(
    portfolio: dict[str, Any], snapshots: list[dict[str, Any]], *, generated_at: str | None = None,
    _include_views: bool = True, source_dir: Path | None = None, performance_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = portfolio.get("settings", {})
    profile = portfolio.get("profile", {})
    holdings = portfolio.get("holdings", [])
    normalized_holdings = (
        [h for h in holdings if isinstance(h, dict)]
        if isinstance(holdings, list)
        else []
    )

    report_preferences = portfolio.get("extensions", {}).get("rikdom_report")
    if not isinstance(report_preferences, dict):
        report_preferences = {}
    report_language = report_preferences.get("locale", settings.get("language", "en"))
    asset_type_catalog = portfolio.get("asset_type_catalog", [])
    base_currency = str(settings.get("base_currency", "USD")).upper().strip() or "USD"

    fx_lock = _latest_fx_lock(snapshots, base_currency=base_currency)
    result = aggregate_portfolio(portfolio, fx_rates_to_base=fx_lock.get("rates_to_base"))
    result.fx_lock = fx_lock or None
    generated_at = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    trust_reports = build_trust_reports(
        result, portfolio_id=str(portfolio.get("portfolio_id", portfolio.get("id", "portfolio"))),
        generated_at=generated_at,
    )
    quality_warnings = list(result.warnings)
    for holding in trust_reports["holding_trust"]["holdings"]:
        if holding.get("fx_source") not in {"fx_rates_to_base", "metadata.fx_rate_to_base"}:
            continue
        currency = holding.get("source_currency", "unknown")
        effective = holding.get("fx_timestamp")
        if not effective:
            quality_warnings.append(f"FX effective date unknown for {currency}; report generation time is not a rate date.")
        elif effective[:10] < generated_at[:10]:
            quality_warnings.append(f"FX rate for {currency} predates report generation: effective {effective}.")

    by_currency: dict[str, float] = {}
    by_asset_type: dict[str, float] = {}
    geo: dict[str, float] = {}
    top_holdings: list[dict[str, Any]] = []
    for holding, record in zip(normalized_holdings, result.trust_records):
        currency = _normalize_currency_code(record.source_currency)
        if record.source_amount is not None:
            by_currency[currency] = by_currency.get(currency, 0.0) + record.source_amount
        market_value = holding.get("market_value")
        raw_amount = _safe_float(market_value.get("amount")) if isinstance(market_value, dict) else None
        top_holdings.append({
            "id": record.holding_id, "label": str(holding.get("label", "")),
            "amount": raw_amount if raw_amount is not None else 0.0, "currency": currency,
            "base_amount": record.base_amount, "excluded_reason": record.excluded_reason,
        })
        if record.excluded_reason is not None or record.base_amount is None:
            continue
        bucket = _asset_type_bucket(record.asset_type_id, record.asset_class)
        by_asset_type[bucket] = by_asset_type.get(bucket, 0.0) + record.base_amount
        jurisdiction = holding.get("jurisdiction", {})
        country = str(jurisdiction.get("country", "")).upper().strip() if isinstance(jurisdiction, dict) else ""
        if not country:
            country = str(profile.get("country", "")).upper().strip() or "UNKNOWN"
        geo[country] = geo.get(country, 0.0) + record.base_amount
    top_holdings = sorted(
        top_holdings,
        key=lambda item: (item["base_amount"] is not None, item["base_amount"] or 0.0, item["amount"]),
        reverse=True,
    )[:5]

    chronological_snapshots: list[tuple[datetime, dict[str, Any]]] = []
    unavailable_snapshots: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        totals = snapshot.get("totals", {})
        if not isinstance(totals, dict):
            continue
        value = totals.get("portfolio_value_base")
        if not isinstance(value, (int, float)):
            continue
        row = {
            "timestamp": snapshot.get("timestamp"),
            "portfolio_value_base": float(value),
            "by_asset_class": totals.get("by_asset_class", {}),
        }
        timestamp = snapshot.get("timestamp")
        try:
            if not isinstance(timestamp, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", timestamp
            ):
                raise ValueError("Snapshot timestamp needs an explicit source offset")
            instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            unavailable_snapshots.append(row)
            quality_warnings.append(
                f"Snapshot timestamp {timestamp!r} is missing or invalid; excluded from chronological history."
            )
            continue
        chronological_snapshots.append((instant, row))
    # All renderers and historical metrics consume this same order. Calendar
    # filters/display retain the timestamp's written date and explicit offset.
    chronological_snapshots.sort(key=lambda item: item[0])
    timeline = [row for _, row in chronological_snapshots]

    latest_by_asset_class: dict[str, float] = {}
    if timeline:
        maybe_latest = timeline[-1].get("by_asset_class")
        if isinstance(maybe_latest, dict):
            for key, value in maybe_latest.items():
                parsed = _safe_float(value)
                if parsed is not None and parsed > 0:
                    latest_by_asset_class[str(key)] = parsed

    quickview_currency = _build_quickview_currency_split(result.trust_records)
    reconciliation = trust_reports["reconciliation"]
    reconciliation["warnings"] = list(dict.fromkeys(quality_warnings))
    quality = {
        "summary": reconciliation["summary"],
        "coverage": reconciliation["coverage_summary"],
        "quantity": reconciliation["quantity_summary"],
        "warnings": list(dict.fromkeys(quality_warnings)),
        "excluded_holding_ids": trust_reports["holding_trust"]["invariant"]["excluded_holding_ids"],
        "artifacts": [
            {"label": f"{label} ({extension.upper()})", "href": f"{name}.{extension}"}
            for extension in ("json", "md")
            for name, label in (("holding_trust", "Holding trust"), ("reconciliation", "Reconciliation"))
        ],
    }

    payload = {
        "profile": {
            "display_name": profile.get("display_name", "Portfolio"),
            "country": profile.get("country"),
            "base_currency": base_currency,
            "timezone": settings.get("timezone"),
            "language": "pt" if str(report_language).lower().startswith("pt") else "en",
        },
        "asset_type_catalog": asset_type_catalog,
        "trust_reports": trust_reports,
        "sections": {
            "current_valuation": {
                "total_value_base": result.total_value_base,
                "base_currency": result.base_currency,
                "by_asset_class": result.by_asset_class,
                "fx_context": fx_lock,
                "generated_at": generated_at,
            },
            "data_quality": quality,
            "timeline": timeline,
            "unavailable_snapshots": unavailable_snapshots,
            "snapshot_date_convention": "Source calendar date at the timestamp explicit offset; inclusive bounds; chronology ordered by instant.",
            "currency_split": by_currency,
            "asset_type_breakdown": by_asset_type,
            "geography": geo,
            "risk": {
                "top_holdings": top_holdings,
                "fx_non_base_share_hint": "computed from currency_split vs base_currency",
            },
            "quickview": {
                "latest_by_asset_class": latest_by_asset_class,
                "currency": quickview_currency,
            },
        },
    }

    # All displayed financial ratios and changes are computed here. JavaScript
    # may scale chart coordinates, but never derives a return or income metric.
    total = result.total_value_base
    history_values = [row["portfolio_value_base"] for row in timeline]
    first = history_values[0] if history_values else None
    latest = history_values[-1] if history_values else None
    previous = history_values[-2] if len(history_values) > 1 else None
    presentation = {
        "history": {
            "interval_change": latest - previous if previous is not None else None,
            "interval_change_fraction": (latest - previous) / previous if previous else None,
            "total_change": latest - first if len(history_values) > 1 else None,
            "total_change_fraction": (latest - first) / first if first and len(history_values) > 1 else None,
        },
        "largest_holding_share": (top_holdings[0].get("base_amount") or 0) / total if total and top_holdings else None,
        "largest_currency_share": max(quickview_currency["converted_base"].values(), default=0) / total if total else None,
        "holding_shares": {row["id"]: row["base_amount"] / total if row["base_amount"] is not None and total else None for row in top_holdings},
        "allocation_shares": {},
    }
    for title, amounts in (
        ("Current currency allocation", quickview_currency["converted_base"]),
        ("Asset type breakdown", by_asset_type), ("Geography", geo),
        ("Current allocation by asset class", result.by_asset_class),
    ):
        positive_total = sum(value for value in amounts.values() if value > 0)
        presentation["allocation_shares"][title] = {key: value / positive_total if positive_total else None for key, value in amounts.items()}
    payload["sections"]["presentation"] = presentation
    if _include_views:
        configured = report_preferences.get('performance')
        explicit_replay = bool((performance_options or {}).get('historical_valuations')) or (
            isinstance(configured, dict) and 'historical_valuations_path' in configured)
        if unavailable_snapshots and not explicit_replay:
            performance, performance_context = None, {
                "status": "unavailable", "scope": "portfolio",
                "warnings": ["Performance unavailable: snapshot history contains invalid or missing timestamps; review data-quality warnings."],
            }
        else:
            performance, performance_context = _build_performance_section(
                portfolio, snapshots, report_preferences, source_dir=source_dir or Path("."), generated_at=generated_at, overrides=performance_options,
            )
        payload["sections"].update(performance=performance, performance_context=performance_context)
    else:
        payload["sections"].update(performance=None, performance_context={"status": "unavailable_for_scope"})
    if _include_views:
        income = build_income_report(portfolio)
        contributions = recorded_contributions(portfolio.get('activities', []))
        payload["sections"].update(income=income, contributions=contributions, historical_status="recorded")
        # A single asserted dimension per view keeps the artifact linear in the
        # number of accounts/types/currencies. Today's holdings never attribute
        # historical snapshots or activities to a scope.
        views = []
        for dimension in ("account_id", "asset_type_id", "currency"):
            def identity(row):
                if dimension == "currency":
                    money = row.get("market_value")
                    return money.get("currency") if isinstance(money, dict) else None
                return row.get(dimension)
            values = {identity(row) for row in normalized_holdings}
            values.update(row.get(dimension) for row in income["events"])
            values.update(row.get(dimension) for row in contributions)
            for key in ("announced", "estimates", "reconciliation", "yield_on_cost"):
                values.update((row.get("currency") if dimension == "currency" else row.get("scope", {}).get(dimension))
                              for row in income.get("planning", {}).get(key, []))
            for value in sorted(v for v in values if isinstance(v, str) and v):
                scoped = copy.deepcopy(portfolio)
                scoped["holdings"] = [row for row in normalized_holdings if identity(row) == value]
                # Preserve the original FX lock for current scoped valuations.
                context = [{"metadata": {"fx_lock": fx_lock}}] if fx_lock else []
                scoped_sections = _build_report_payload(scoped, context, generated_at=generated_at, _include_views=False)["sections"]
                scoped_income = copy.deepcopy(income)
                scoped_income["events"] = [row for row in income["events"] if row.get(dimension) == value]
                # Whole-portfolio received buckets cannot be relabelled as
                # scoped totals. The UI renders individual asserted records.
                scoped_income["monthly"] = []
                scoped_income["yearly"] = []
                selected_ids = {row["activity_id"] for row in scoped_income["events"]}
                scoped_income["diagnostics"] = [row for row in income["diagnostics"] if row.get("activity_id") in selected_ids]
                if "planning" in scoped_income:
                    planning = scoped_income["planning"]
                    for key in ("announced", "estimates", "reconciliation", "yield_on_cost"):
                        planning[key] = [row for row in planning.get(key, []) if
                                         (row.get("currency") if dimension == "currency" else row.get("scope", {}).get(dimension)) == value]
                    planning["diagnostics"] = []
                scoped_sections.update(
                    income=scoped_income,
                    contributions=[row for row in contributions if row.get(dimension) == value],
                    historical_status="unavailable_for_scope",
                )
                views.append({"dimension": dimension, "value": value, "sections": scoped_sections})
        payload["report_views"] = views
    return payload


def _write_fallback_html(
    path: Path, reason: str, link_href: str, link_label: str,
    *, payload: dict[str, Any] | None = None,
) -> None:
    sections = (payload or {}).get("sections", {})
    quality = sections.get("data_quality", {})
    valuation = sections.get("current_valuation", {})
    timeline = sections.get("timeline", [])
    historical = timeline[-1] if timeline else {}
    warnings = "".join(f"<li>{escape(str(warning))}</li>" for warning in quality.get("warnings", []))
    links = " ".join(f'<a href="{escape(item["href"])}">{escape(item["label"])}</a>' for item in quality.get("artifacts", []))
    quality_html = (
        "<section><h2>Current valuation</h2>"
        f"<p>{escape(str(valuation.get('total_value_base', 'unknown')))} {escape(str(valuation.get('base_currency', '')))}; current holdings, report generated {escape(str(valuation.get('generated_at', 'unknown')))}.</p>"
        "<h2>Historical snapshot</h2>"
        f"<p>{escape(str(historical.get('portfolio_value_base', 'unknown')))} as of {escape(str(historical.get('timestamp', 'unknown')))}.</p>"
        "<h2>Data quality</h2>"
        f"<p>History coverage: {escape(str(quality.get('coverage', {}).get('status', 'unknown')))}. Zero findings do not prove complete history.</p>"
        f"<p>Quantity: {escape(str(quality.get('quantity', {})))}</p>"
        f"<p>Excluded holdings: {escape(', '.join(quality.get('excluded_holding_ids', [])) or 'none')}</p>"
        f"<ul>{warnings}</ul><p>{links}</p></section>"
    )
    path.write_text(
        (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>rikdom fallback Portfolio Report</title>'
            '<style>body{max-width:70rem;margin:0 auto;padding:1rem;overflow-wrap:anywhere;}'
            'a{display:inline-block;margin:.25rem 0;}'
            'a:focus-visible{outline:2px solid currentColor;outline-offset:2px;}</style>'
            '</head><body><main id="fallback-app" ' + f'data-reason="{escape(reason, quote=True)}" data-sibling="{escape(link_href, quote=True)}">'
            "<h1>Fallback Portfolio Report</h1>"
            f"<p>{escape(reason)}</p>"
            f'<p><a href="{escape(link_href)}">{escape(link_label)}</a></p>'
            + quality_html + '</main><script src="report-data.js"></script><script>if(window.RIKDOM_REPORT) window.RIKDOM_REPORT.mountFallback();</script></body></html>'
        ),
        encoding="utf-8",
    )


def _find_quarto_bin() -> str | None:
    if os.environ.get("RIKDOM_DISABLE_QUARTO"):
        return None
    quarto_bin = shutil.which("quarto")
    if quarto_bin:
        return quarto_bin

    exe_parent = Path(sys.executable).parent
    prefix_bin = Path(sys.prefix) / "bin"
    base_prefix_bin = Path(sys.base_prefix) / "bin"
    resolved_parent = Path(sys.executable).resolve().parent
    candidates = [
        exe_parent / "quarto",
        exe_parent / "quarto.exe",
        prefix_bin / "quarto",
        prefix_bin / "quarto.exe",
        base_prefix_bin / "quarto",
        base_prefix_bin / "quarto.exe",
        resolved_parent / "quarto",
        resolved_parent / "quarto.exe",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None


def _prepare_render_workspace(
    templates_dir: Path,
    payload: dict[str, Any],
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    tmp_dir = tempfile.TemporaryDirectory()
    render_dir = Path(tmp_dir.name)

    for source in templates_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, render_dir / source.name)

    data_js = render_dir / "report-data.js"
    data_js.write_text(
        "window.RIKDOM_REPORT_DATA = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n" + (templates_dir / "report-runtime.js").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    return tmp_dir, render_dir


def _render_qmd(
    *,
    quarto_bin: str,
    render_dir: Path,
    out_dir: Path,
    template_name: str,
    output_name: str,
) -> tuple[bool, str | None]:
    command = [
        quarto_bin,
        "render",
        template_name,
        "--to",
        "html",
        "--output",
        output_name,
        "--output-dir",
        str(out_dir),
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(render_dir),
            text=True,
            capture_output=True,
            check=False,
            timeout=QUARTO_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            f"Quarto render timed out after {QUARTO_TIMEOUT_SECONDS}s for {template_name}. Generated fallback HTML artifact.",
        )
    except OSError as exc:
        return (
            False,
            f"Quarto execution error for {template_name}: {exc}. Generated fallback HTML artifact.",
        )

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if detail:
            return (
                False,
                f"Quarto render failed for {template_name}: {detail}. Generated fallback HTML artifact.",
            )
        return (
            False,
            f"Quarto render failed with non-zero exit code for {template_name}. Generated fallback HTML artifact.",
        )

    return True, None


class Plugin:
    @hookimpl
    def output(self, ctx, request):
        portfolio = load_json(request.portfolio_path)
        snapshots = load_jsonl(request.snapshots_path)
        out_dir = Path(request.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        payload = _build_report_payload(portfolio, snapshots, source_dir=Path(request.portfolio_path).resolve().parent,
                                        performance_options=request.options)
        trust_artifacts = write_trust_reports(payload["trust_reports"], out_dir)
        payload_path = out_dir / "quarto-input.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        runtime_path = Path(__file__).resolve().parent / "templates" / "report-runtime.js"
        runtime = runtime_path.read_text(encoding="utf-8") if runtime_path.exists() else ""
        output_js_path = out_dir / "report-data.js"
        output_js_path.write_text(
            "window.RIKDOM_REPORT_DATA = "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + ";\n" + runtime,
            encoding="utf-8",
        )

        report_path = out_dir / REPORT_FILENAME
        quickview_path = out_dir / QUICKVIEW_FILENAME
        warnings: list[str] = []

        templates_dir = Path(__file__).resolve().parent / "templates"
        required_templates = {
            "report.qmd": report_path,
            "dashboard.qmd": quickview_path,
            "report-runtime.js": output_js_path,
        }
        missing_templates = [
            name for name in required_templates if not (templates_dir / name).exists()
        ]
        if missing_templates:
            warning = (
                "Missing Quarto template(s): "
                + ", ".join(str(templates_dir / name) for name in missing_templates)
                + ". Generated fallback HTML artifacts."
            )
            warnings.append(warning)
            _write_fallback_html(
                report_path, warning, QUICKVIEW_FILENAME, "Open dashboard quickview", payload=payload
            )
            _write_fallback_html(
                quickview_path,
                warning,
                REPORT_FILENAME,
                "Open deep-dive report", payload=payload,
            )
        else:
            quarto_bin = _find_quarto_bin()
            if not quarto_bin:
                warning = "Quarto binary 'quarto' not found in PATH. Generated fallback HTML artifacts."
                warnings.append(warning)
                _write_fallback_html(
                    report_path, warning, QUICKVIEW_FILENAME, "Open dashboard quickview", payload=payload
                )
                _write_fallback_html(
                    quickview_path,
                    warning,
                    REPORT_FILENAME,
                    "Open deep-dive report", payload=payload,
                )
            else:
                tmp_dir, render_dir = _prepare_render_workspace(templates_dir, payload)
                try:
                    rendered_report, report_warning = _render_qmd(
                        quarto_bin=quarto_bin,
                        render_dir=render_dir,
                        out_dir=out_dir.resolve(),
                        template_name="report.qmd",
                        output_name=REPORT_FILENAME,
                    )
                    rendered_quickview, quickview_warning = _render_qmd(
                        quarto_bin=quarto_bin,
                        render_dir=render_dir,
                        out_dir=out_dir.resolve(),
                        template_name="dashboard.qmd",
                        output_name=QUICKVIEW_FILENAME,
                    )
                finally:
                    tmp_dir.cleanup()

                if report_warning:
                    warnings.append(report_warning)
                if quickview_warning:
                    warnings.append(quickview_warning)

                if not rendered_report:
                    _write_fallback_html(
                        report_path,
                        report_warning or "Failed to render report.qmd.",
                        QUICKVIEW_FILENAME,
                        "Open dashboard quickview", payload=payload,
                    )
                if not rendered_quickview:
                    _write_fallback_html(
                        quickview_path,
                        quickview_warning or "Failed to render dashboard.qmd.",
                        REPORT_FILENAME,
                        "Open deep-dive report", payload=payload,
                    )

        if not report_path.exists():
            warning = f"Expected report artifact was not created: {report_path}. Generated fallback HTML artifact."
            warnings.append(warning)
            _write_fallback_html(
                report_path, warning, QUICKVIEW_FILENAME, "Open dashboard quickview", payload=payload
            )

        if not quickview_path.exists():
            warning = f"Expected quickview artifact was not created: {quickview_path}. Generated fallback HTML artifact."
            warnings.append(warning)
            _write_fallback_html(
                quickview_path, warning, REPORT_FILENAME, "Open deep-dive report", payload=payload
            )

        return {
            "plugin": "quarto-portfolio-report",
            "artifacts": [
                {"type": "html", "path": str(report_path)},
                {"type": "html_dashboard", "path": str(quickview_path)},
                {"type": "json", "path": str(payload_path)},
                {"type": "js", "path": str(output_js_path)},
                *trust_artifacts,
            ],
            "warnings": warnings,
        }
