"""Capture and replay the installed core's aggregate calculation, without plugins.

The run format owns method dispatch, environment requirements, financial equality
and fresh-directory restoration. It never imports or installs bundled code.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .aggregate import aggregate_portfolio
from .export_bundle import (
    AGGREGATE_EXPORT_VERSION,
    MANIFEST_PATH,
    ExportBundleError,
    create_export_bundle,
    read_verified_payloads,
)
from .validate import validate_portfolio

RUN_VERSION = "1.0.0"
METHOD = {"name": "aggregate", "version": "1.0.0"}
EQUALITY = {"absolute_tolerance": 1e-8, "relative_tolerance": 1e-12}
PAYLOAD_PATHS = {
    "portfolio": "data/portfolio.json",
    "analysis_run": "analysis/run.json",
    "analysis_result": "analysis/result.json",
    "dependency_lock": "environment/uv.lock",
}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _environment() -> dict[str, Any]:
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for source in sorted(root.rglob("*.py")):
        digest.update(source.relative_to(root).as_posix().encode() + b"\0")
        digest.update(source.read_bytes())
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "core_version": version("rikdom"),
        "core_sha256": digest.hexdigest(),
        "plugins": [],
        "dependencies": {
            name: version(name) for name in ("jsonschema", "rfc3339-validator")
        },
    }


def aggregate_output(
    portfolio: dict[str, Any],
    *,
    strict: bool,
    fx_lock: dict[str, Any],
    fx_warnings: list[str],
) -> dict[str, Any]:
    """Return the same deterministic, unrounded result for CLI and run replay."""
    result = aggregate_portfolio(
        portfolio,
        strict=strict,
        fx_rates_to_base=fx_lock.get("rates_to_base"),
    )
    output: dict[str, Any] = {
        "base_currency": result.base_currency,
        "portfolio_value_base": result.total_value_base,
        "by_asset_class": result.by_asset_class,
        "warnings": result.warnings + fx_warnings,
        "errors": result.errors,
    }
    for key in (
        "by_region",
        "by_currency",
        "by_duration",
        "by_liquidity_tier",
        "by_account",
    ):
        value = getattr(result, key)
        if value:
            output[key] = value
    return output


def capture_aggregate_bundle(
    output: str | Path,
    *,
    portfolio: dict[str, Any],
    strict: bool,
    fx_lock: dict[str, Any],
    fx_warnings: list[str],
    result: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    """Bundle the actual in-memory inputs and result, independently of workspace files."""
    errors = validate_portfolio(portfolio)
    if errors:
        raise ExportBundleError(
            "Cannot capture invalid portfolio: " + "; ".join(errors)
        )
    if result.get("errors"):
        raise ExportBundleError("Cannot capture a failed calculation")
    inputs = _json_bytes(portfolio)
    result_bytes = _json_bytes(result)
    lock_path = Path(__file__).resolve().parents[2] / "uv.lock"
    lock = lock_path.read_bytes() if lock_path.is_file() else None
    if Path(output).resolve() == lock_path:
        raise ExportBundleError("Refusing to overwrite dependency lock")
    run = {
        "format": "rikdom-analysis-run",
        "format_version": RUN_VERSION,
        "created_at": created_at,
        "method": METHOD,
        "parameters": {
            "strict": strict,
            "fx_lock": fx_lock,
            "fx_warnings": fx_warnings,
        },
        "inputs": {
            "portfolio": {"path": PAYLOAD_PATHS["portfolio"], "sha256": _sha256(inputs)}
        },
        "result": {
            "path": PAYLOAD_PATHS["analysis_result"],
            "sha256": _sha256(result_bytes),
        },
        "equality": EQUALITY,
        "environment": _environment(),
        "dependency_lock": (
            {
                "status": "included",
                "path": PAYLOAD_PATHS["dependency_lock"],
                "sha256": _sha256(lock),
            }
            if lock is not None
            else {
                "status": "unavailable",
                "reason": "uv.lock is not installed with this runtime",
            }
        ),
        "scope": "Normalized aggregate inputs only; no importer, historical-return or report replay",
    }
    with TemporaryDirectory() as directory:
        stage = Path(directory)
        for name, data in (
            ("portfolio.json", inputs),
            ("run.json", _json_bytes(run)),
            ("result.json", result_bytes),
        ):
            (stage / name).write_bytes(data)
        if lock is not None:
            (stage / "uv.lock").write_bytes(lock)
        return create_export_bundle(
            output,
            created_at=created_at,
            portfolio=stage / "portfolio.json",
            analysis_run=stage / "run.json",
            analysis_result=stage / "result.json",
            dependency_lock=stage / "uv.lock" if lock is not None else None,
        )


def _decode_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        result = json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ExportBundleError(f"Invalid {label} JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ExportBundleError(f"Invalid {label}: expected object")
    return result


def _equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return (
            math.isfinite(expected)
            and math.isfinite(actual)
            and math.isclose(
                expected,
                actual,
                rel_tol=EQUALITY["relative_tolerance"],
                abs_tol=EQUALITY["absolute_tolerance"],
            )
        )
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(
            _equal(expected[key], actual[key]) for key in expected
        )
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            _equal(a, b) for a, b in zip(expected, actual)
        )
    return type(expected) is type(actual) and expected == actual


def _validate_fx_lock(lock: dict[str, Any], base_currency: str) -> None:
    required = {
        "base_currency",
        "snapshot_timestamp",
        "rates_to_base",
        "rate_dates",
        "sources",
    }
    if set(lock) != required or lock["base_currency"] != base_currency:
        raise ExportBundleError(
            "Invalid aggregate FX lock: fields/base currency mismatch"
        )
    timestamp = lock["snapshot_timestamp"]
    try:
        if not isinstance(timestamp, str):
            raise ValueError("timestamp must be a string")
        as_of = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if as_of.tzinfo is None:
            raise ValueError("timestamp requires an explicit timezone")
        cutoff = as_of.astimezone(timezone.utc).date()
    except ValueError as exc:
        raise ExportBundleError(f"Invalid aggregate FX lock: {exc}") from exc
    rates, dates, sources = (
        lock[key] for key in ("rates_to_base", "rate_dates", "sources")
    )
    if not all(isinstance(value, dict) for value in (rates, dates, sources)) or not (
        rates.keys() == dates.keys() == sources.keys()
    ):
        raise ExportBundleError("Invalid aggregate FX lock: missing rate dates/sources")
    for currency, rate in rates.items():
        try:
            if (
                not isinstance(currency, str)
                or len(currency) != 3
                or not currency.isascii()
                or not currency.isalpha()
                or currency != currency.upper()
                or currency == base_currency
                or isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not math.isfinite(rate)
                or rate <= 0
            ):
                raise ValueError("invalid currency/rate")
            effective_date = dates[currency]
            if not isinstance(effective_date, str):
                raise ValueError("rate date must be a string")
            parsed_date = date.fromisoformat(effective_date)
            if parsed_date.isoformat() != effective_date or parsed_date > cutoff:
                raise ValueError(
                    "rate date exceeds the valuation cutoff or is not ISO format"
                )
            if not isinstance(sources[currency], str) or not sources[currency]:
                raise ValueError("rate source must be a nonempty string")
        except (ValueError, OverflowError) as exc:
            raise ExportBundleError(
                f"Invalid aggregate FX lock for {currency}: {exc}"
            ) from exc


def replay_aggregate_bundle(
    bundle: str | Path, restore_dir: str | Path
) -> dict[str, Any]:
    """Verify, reproduce with installed core code, then publish a fresh workspace.

    All archive paths are mapped to fixed destinations; ZIP extraction is never
    used. No target directory is created until verification and replay succeed.
    """
    target = Path(restore_dir)
    if target.exists() or target.is_symlink():
        raise ExportBundleError("Restore directory must not exist")
    manifest, payloads = read_verified_payloads(bundle)
    if manifest["format_version"] != AGGREGATE_EXPORT_VERSION:
        raise ExportBundleError(
            "Bundle has no captured aggregate analysis; use restore-analysis for v2 performance bundles or import-export for v1 data"
        )
    if set(payloads) - PAYLOAD_PATHS.keys():
        raise ExportBundleError("Unsupported inputs for aggregate replay")
    for entry in manifest["entries"]:
        if entry["path"] != PAYLOAD_PATHS[entry["kind"]]:
            raise ExportBundleError("Unsupported analysis payload path")
    run = _decode_object(payloads["analysis_run"], "run manifest")
    if (
        run.get("format") != "rikdom-analysis-run"
        or run.get("format_version") != RUN_VERSION
    ):
        raise ExportBundleError("Unsupported analysis run format")
    if run.get("method") != METHOD:
        raise ExportBundleError("Unsupported calculation method/version")
    if run.get("equality") != EQUALITY:
        raise ExportBundleError("Unsupported financial equality conventions")
    for label, expected in (
        (
            "inputs",
            {
                "portfolio": {
                    "path": PAYLOAD_PATHS["portfolio"],
                    "sha256": _sha256(payloads["portfolio"]),
                }
            },
        ),
        (
            "result",
            {
                "path": PAYLOAD_PATHS["analysis_result"],
                "sha256": _sha256(payloads["analysis_result"]),
            },
        ),
    ):
        if run.get(label) != expected:
            raise ExportBundleError(f"Analysis {label} reference mismatch")
    lock = run.get("dependency_lock")
    if "dependency_lock" in payloads:
        expected_lock = {
            "status": "included",
            "path": PAYLOAD_PATHS["dependency_lock"],
            "sha256": _sha256(payloads["dependency_lock"]),
        }
        if lock != expected_lock:
            raise ExportBundleError("Dependency lock reference mismatch")
    elif not isinstance(lock, dict) or lock.get("status") != "unavailable":
        raise ExportBundleError("Missing dependency lock")
    if run.get("environment") != _environment():
        raise ExportBundleError(
            "Incompatible runtime/core/dependency environment; install matching requirements explicitly"
        )
    parameters = run.get("parameters")
    if (
        not isinstance(parameters, dict)
        or set(parameters) != {"strict", "fx_lock", "fx_warnings"}
        or not isinstance(parameters.get("strict"), bool)
        or not isinstance(parameters.get("fx_lock"), dict)
        or not isinstance(parameters.get("fx_warnings"), list)
        or any(not isinstance(item, str) for item in parameters["fx_warnings"])
        or not isinstance(parameters["fx_lock"].get("rates_to_base"), dict)
    ):
        raise ExportBundleError("Invalid aggregate parameters")
    portfolio = _decode_object(payloads["portfolio"], "portfolio")
    errors = validate_portfolio(portfolio)
    if errors:
        raise ExportBundleError("Invalid captured portfolio: " + "; ".join(errors))
    _validate_fx_lock(
        parameters["fx_lock"], portfolio["settings"]["base_currency"].strip().upper()
    )
    expected_result = _decode_object(payloads["analysis_result"], "result")
    actual = aggregate_output(portfolio, **parameters)
    if actual["errors"] or not _equal(expected_result, actual):
        raise ExportBundleError(
            "Reproduced financial result does not match captured result"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent, prefix=".rikdom-restore-") as directory:
        stage = Path(directory) / "workspace"
        stage.mkdir()
        for kind, data in payloads.items():
            destination = stage / PAYLOAD_PATHS[kind]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (stage / MANIFEST_PATH).write_bytes(_json_bytes(manifest))
        if target.exists() or target.is_symlink():
            raise ExportBundleError("Restore directory must not exist")
        stage.rename(target)
    return {"status": "reproduced", "restore_dir": str(target), "result": actual}
