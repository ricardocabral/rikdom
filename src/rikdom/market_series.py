"""Strict, read-only replay of version 1.0 local price and FX JSON files.

``load_market_series(path).lookup(...)`` hides validation, revision chains and
historical selection. Effective time controls market selection; the optional
retrieval cutoff controls knowledge. No clock, provider, or portfolio is used.
"""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypedDict


class LookupResult(TypedDict):
    status: Literal["available", "missing", "stale"]
    reason: str | None
    series_id: str
    as_of: str
    max_age_seconds: float
    retrieved_before: str | None
    age_seconds: float | None
    series: dict[str, Any] | None
    observation: dict[str, Any] | None
    superseded: list[dict[str, Any]]


@dataclass(frozen=True)
class _Observation:
    effective: datetime
    retrieved: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class _Series:
    metadata: dict[str, Any]
    start: datetime
    end: datetime
    observations: tuple[_Observation, ...]


def _object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a non-blank string without surrounding whitespace")
    return value


def _currency(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency must be a three-letter uppercase code")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    # Restrict syntax rather than inheriting fromisoformat's permissive date forms.
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value
    ):
        raise ValueError(f"{label} must be an explicit UTC timestamp (Z or +00:00)")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{label} must be a valid UTC timestamp") from None


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _number(value: Any, *, positive: bool) -> float:
    try:
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and (value > 0 if positive else value >= 0))
    except OverflowError:
        valid = False
    if not valid:
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"numeric value must be finite and {qualifier}; booleans are invalid")
    return float(value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _parse_series(raw: Any) -> tuple[str, _Series]:
    kind = raw.get("kind") if isinstance(raw, dict) else None
    if kind not in ("price", "fx"):
        raise ValueError("series.kind must be price or fx")
    identity_field = "instrument" if kind == "price" else "currency_pair"
    row = _object(raw, {"id", "kind", identity_field, "currency", "adjustment", "coverage", "license", "observations"}, "series")
    sid = _text(row["id"], "series.id")
    currency = _currency(row["currency"])
    if kind == "price":
        instrument = _object(row["instrument"], {"namespace", "id", "currency"}, "instrument")
        _text(instrument["namespace"], "instrument.namespace")
        _text(instrument["id"], "instrument.id")
        if _currency(instrument["currency"]) != currency:
            raise ValueError("instrument currency must match series currency")
        if row["adjustment"] not in ("unadjusted", "split_adjusted", "total_return_adjusted"):
            raise ValueError("price adjustment must be unadjusted, split_adjusted or total_return_adjusted")
    else:
        pair = _object(row["currency_pair"], {"base", "quote"}, "currency_pair")
        base, quote = _currency(pair["base"]), _currency(pair["quote"])
        if base == quote or quote != currency:
            raise ValueError("FX requires distinct base/quote currencies and series currency equal to quote")
        if row["adjustment"] != "not_applicable":
            raise ValueError("FX adjustment must be not_applicable")
    coverage = _object(row["coverage"], {"start", "end"}, "coverage")
    start = _timestamp(coverage["start"], "coverage.start")
    end = _timestamp(coverage["end"], "coverage.end")
    if start > end:
        raise ValueError("coverage.start must not exceed coverage.end")
    license_info = _object(row["license"], {"name", "uri"}, "license")
    _text(license_info["name"], "license.name")
    _text(license_info["uri"], "license.uri")
    rows = row["observations"]
    if not isinstance(rows, list):
        raise ValueError("observations must be an array")
    observations: dict[str, _Observation] = {}
    roots: set[datetime] = set()
    superseded: set[str] = set()
    for item in rows:
        payload = _object(item, {"id", "effective_at", "retrieved_at", "source", "value", "currency", "supersedes"}, "observation")
        oid = _text(payload["id"], "observation.id")
        if oid in observations:
            raise ValueError("duplicate observation id")
        effective = _timestamp(payload["effective_at"], "effective_at")
        retrieved = _timestamp(payload["retrieved_at"], "retrieved_at")
        if not start <= effective <= end or retrieved < effective:
            raise ValueError("observation must be within coverage and retrieved at or after effective time")
        _text(payload["source"], "source")
        _number(payload["value"], positive=True)
        if _currency(payload["currency"]) != currency:
            raise ValueError("observation currency must match series currency")
        previous = payload["supersedes"]
        if previous is not None:
            _text(previous, "supersedes")
        elif effective in roots:
            raise ValueError("ambiguous observations: each effective timestamp requires one revision root")
        else:
            roots.add(effective)
        normalized = {**payload, "effective_at": _iso(effective), "retrieved_at": _iso(retrieved)}
        observations[oid] = _Observation(effective, retrieved, normalized)
    for item in observations.values():
        previous = item.payload["supersedes"]
        if previous is None:
            continue
        parent = observations.get(previous)
        if (parent is None or parent.effective != item.effective or parent.retrieved >= item.retrieved
                or previous in superseded):
            raise ValueError("corrections must form one strictly later retrieval chain for the same effective timestamp")
        superseded.add(previous)
    metadata = {key: copy.deepcopy(value) for key, value in row.items() if key != "observations"}
    metadata["coverage"] = {"start": _iso(start), "end": _iso(end)}
    return sid, _Series(metadata, start, end, tuple(sorted(
        observations.values(), key=lambda item: (item.effective, item.retrieved)
    )))


class MarketSeries:
    """Validated local series. Use ``load_market_series`` to construct this store."""

    def __init__(self, series: dict[str, _Series]):
        self._series = series

    def lookup(
        self, series_id: str, *, as_of: str, max_age_seconds: float,
        retrieved_before: str | None = None,
    ) -> LookupResult:
        """Select latest effective quote <= as_of, then its latest known revision.

        Retrieval cutoff is inclusive. Omitting it uses all vintages in the
        file, including later corrections to historical observations. Age is
        measured from effective time, inclusive at the maximum. Missing/stale
        data never falls back to a future quote, another series, or a provider.
        """
        _text(series_id, "series_id")
        when = _timestamp(as_of, "as_of")
        age_limit = _number(max_age_seconds, positive=False)
        cutoff = _timestamp(retrieved_before, "retrieved_before") if retrieved_before is not None else None
        series = self._series.get(series_id)
        result: LookupResult = {
            "status": "missing", "reason": "unknown_series", "series_id": series_id,
            "as_of": _iso(when), "max_age_seconds": age_limit,
            "retrieved_before": _iso(cutoff) if cutoff else None, "age_seconds": None,
            "series": copy.deepcopy(series.metadata) if series else None,
            "observation": None, "superseded": [],
        }
        if series is None:
            return result
        if not series.start <= when <= series.end:
            result["reason"] = "outside_declared_coverage"
            return result
        eligible = [item for item in series.observations
                    if item.effective <= when and (cutoff is None or item.retrieved <= cutoff)]
        if not eligible:
            result["reason"] = "no_eligible_observation"
            return result
        selected = eligible[-1]
        age = (when - selected.effective) / timedelta(seconds=1)
        result.update(status="stale" if age > age_limit else "available",
                      reason="maximum_age_exceeded" if age > age_limit else None,
                      age_seconds=age, observation=copy.deepcopy(selected.payload),
                      superseded=[copy.deepcopy(item.payload) for item in eligible
                                  if item.effective == selected.effective and item is not selected])
        return result


def load_market_series(path: str | Path) -> MarketSeries:
    """Load one strict versioned JSON file without writing or acquiring data.

    Reject the entire file on invalid metadata, numbers, timestamps, ambiguous
    revisions or unknown fields/versions. No malformed observation is skipped.
    Currency codes are syntactic uppercase codes, not a live ISO registry check.
    """
    with Path(path).open(encoding="utf-8") as handle:
        document = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    return parse_market_series(document)


def parse_market_series(document: Any) -> MarketSeries:
    """Validate and detach an in-memory MarketSeries 1.0 document.

    This shares the file loader's all-or-nothing validation and revision rules.
    Mutating the caller's input cannot change subsequent lookup results.
    """
    document = copy.deepcopy(document)
    document = _object(document, {"contract_version", "series"}, "document")
    if document["contract_version"] != "1.0":
        raise ValueError("unsupported market series contract_version; expected '1.0'")
    if not isinstance(document["series"], list):
        raise ValueError("series must be an array")
    series: dict[str, _Series] = {}
    for raw in document["series"]:
        sid, parsed = _parse_series(raw)
        if sid in series:
            raise ValueError("duplicate series id")
        series[sid] = parsed
    return MarketSeries(series)
