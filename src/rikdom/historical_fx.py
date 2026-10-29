"""Read-only directional historical FX with explicit local-series provenance.

A rate multiplies native value into the reporting currency. Selection never
inverts, triangulates, acquires data, or falls back to undated rates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .market_series import (
    MarketSeries, _currency, _number, _timestamp, _text, _unique_object,
    _reject_constant, load_market_series,
)


@dataclass(frozen=True)
class FxRateResult:
    rate: float | None
    status: str
    reason: str | None
    evidence: dict[str, Any]


class HistoricalFx:
    """Resolve explicit native/reporting pairs at aware activity timestamps."""

    def __init__(
        self, series: MarketSeries, *, base_currency: str,
        series_by_currency: dict[str, str], max_age_seconds: float,
        retrieved_before: str | None = None,
    ):
        self.base_currency = _currency(base_currency)
        if not isinstance(series_by_currency, dict):
            raise ValueError('series_by_currency must be an object')
        self._mapping = {
            _currency(code): _text(sid, 'series id')
            for code, sid in series_by_currency.items()
        }
        self._max_age = _number(max_age_seconds, positive=False)
        self._cutoff = (
            _timestamp(retrieved_before, 'retrieved_before').isoformat().replace('+00:00', 'Z')
            if retrieved_before is not None else None
        )
        self._series = series

    def resolve(self, currency: str, when: datetime) -> FxRateResult:
        native = _currency(currency)
        if not isinstance(when, datetime) or when.tzinfo is None or when.utcoffset() is None:
            raise ValueError('historical FX requires a timezone-aware datetime')
        as_of = when.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        evidence: dict[str, Any] = {
            'as_of': as_of, 'currency_pair': {'base': native, 'quote': self.base_currency},
            'retrieved_before': self._cutoff, 'max_age_seconds': self._max_age,
        }
        if native == self.base_currency:
            evidence.update(status='available', reason=None, rate=1.0, identity=True)
            return FxRateResult(1.0, 'available', None, evidence)
        sid = self._mapping.get(native)
        if sid is None:
            evidence.update(status='missing', reason='missing_currency_mapping', rate=None)
            return FxRateResult(None, 'missing', 'missing_currency_mapping', evidence)
        lookup = self._series.lookup(
            sid, as_of=as_of, max_age_seconds=self._max_age, retrieved_before=self._cutoff,
        )
        evidence.update(lookup)
        metadata = lookup['series']
        if metadata is not None and (
            metadata['kind'] != 'fx'
            or metadata.get('currency_pair') != evidence['currency_pair']
        ):
            evidence.update(status='missing', reason='incompatible_currency_pair')
        rate = None
        if evidence['status'] == 'available':
            rate = _number(lookup['observation']['value'], positive=True)
        evidence['rate'] = rate
        return FxRateResult(rate, evidence['status'], evidence['reason'], evidence)


def load_historical_fx(path: str | Path, *, base_currency: str) -> HistoricalFx:
    """Load strict v1 config and local series; relative paths use config directory."""
    path = Path(path)
    with path.open(encoding='utf-8') as handle:
        config = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    fields = {'contract_version', 'market_series_file', 'series_by_currency',
              'max_age_seconds', 'retrieved_before'}
    if not isinstance(config, dict) or set(config) != fields:
        raise ValueError('historical FX config must contain exactly: ' + ', '.join(sorted(fields)))
    if config['contract_version'] != '1.0':
        raise ValueError("unsupported historical FX contract_version; expected '1.0'")
    series_path = Path(_text(config['market_series_file'], 'market_series_file'))
    if not series_path.is_absolute():
        series_path = path.parent / series_path
    return HistoricalFx(
        load_market_series(series_path), base_currency=base_currency,
        series_by_currency=config['series_by_currency'], max_age_seconds=config['max_age_seconds'],
        retrieved_before=config['retrieved_before'],
    )
