from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .storage import append_jsonl, load_jsonl


FxFetcher = Callable[..., dict[str, float]]


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _snapshot_as_of_date(snapshot_timestamp: str) -> str:
    text = str(snapshot_timestamp or "").strip()
    if not text:
        raise ValueError(
            "snapshot_timestamp is required and must be a non-empty ISO-8601 string"
        )
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"snapshot_timestamp {snapshot_timestamp!r} is not a valid ISO-8601 timestamp"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _normalize_currency(raw: Any) -> str:
    return str(raw or "").strip().upper()


def _required_quote_currencies(
    portfolio: dict[str, Any], *, base_currency: str
) -> list[str]:
    holdings = portfolio.get("holdings")
    if not isinstance(holdings, list):
        return []

    quotes: set[str] = set()
    for holding in holdings:
        if not isinstance(holding, dict):
            continue
        market_value = holding.get("market_value")
        if not isinstance(market_value, dict):
            continue
        currency = _normalize_currency(market_value.get("currency"))
        if len(currency) != 3 or currency == base_currency:
            continue
        quotes.add(currency)

    return sorted(quotes)


def _best_history_rates(
    rows: list[dict[str, Any]],
    *,
    base_currency: str,
    quote_currencies: list[str],
    as_of_date: str,
) -> tuple[dict[str, float], dict[str, str]]:
    quote_set = set(quote_currencies)
    rates: dict[str, float] = {}
    rate_dates: dict[str, str] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_base = _normalize_currency(row.get("base_currency"))
        row_quote = _normalize_currency(row.get("quote_currency"))
        row_date = str(row.get("as_of_date", "")).strip()
        row_rate = row.get("rate_to_base")

        if row_base != base_currency or row_quote not in quote_set:
            continue
        if len(row_date) != 10 or row_date > as_of_date:
            continue
        if not isinstance(row_rate, (int, float)) or row_rate <= 0:
            continue

        current_date = rate_dates.get(row_quote)
        if current_date is None or row_date > current_date:
            rates[row_quote] = float(row_rate)
            rate_dates[row_quote] = row_date

    return rates, rate_dates


def fetch_daily_fx_rates_from_frankfurter(
    *,
    base_currency: str,
    quote_currencies: list[str],
    as_of_date: str,
) -> dict[str, float]:
    rates: dict[str, float] = {}
    for quote_currency in quote_currencies:
        params = urlencode({"from": quote_currency, "to": base_currency})
        url = f"https://api.frankfurter.app/{as_of_date}?{params}"
        request = Request(
            url,
            headers={
                # Frankfurter can reject the default urllib user-agent with 403.
                "User-Agent": "rikdom/1.0 (+https://github.com/ricardocabral/rikdom)",
                "Accept": "application/json",
            },
        )
        # Bandit B310 false positive: endpoint host/scheme are fixed and query params are encoded.
        with urlopen(request, timeout=10) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
        value = payload.get("rates", {}).get(base_currency)
        if isinstance(value, (int, float)) and value > 0:
            rates[quote_currency] = float(value)
    return rates


def ensure_snapshot_fx_lock(
    portfolio: dict[str, Any],
    *,
    fx_history_path: str | Path,
    snapshot_timestamp: str,
    auto_ingest: bool = True,
    fetcher: FxFetcher | None = None,
    extra_quote_currencies: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    settings = portfolio.get("settings") if isinstance(portfolio, dict) else {}
    if not isinstance(settings, dict):
        settings = {}

    base_currency = _normalize_currency(settings.get("base_currency")) or "USD"
    as_of_date = _snapshot_as_of_date(snapshot_timestamp)
    quote_currencies = _required_quote_currencies(
        portfolio, base_currency=base_currency
    )
    if extra_quote_currencies:
        merged = set(quote_currencies)
        for currency in extra_quote_currencies:
            code = _normalize_currency(currency)
            if len(code) == 3 and code != base_currency:
                merged.add(code)
        quote_currencies = sorted(merged)

    rows = load_jsonl(fx_history_path)
    rates_to_base, rate_dates = _best_history_rates(
        rows,
        base_currency=base_currency,
        quote_currencies=quote_currencies,
        as_of_date=as_of_date,
    )
    sources = {currency: "history" for currency in rates_to_base}
    warnings: list[str] = []

    missing = [
        currency for currency in quote_currencies if currency not in rates_to_base
    ]
    if missing and auto_ingest:
        fetch_fn = fetcher or fetch_daily_fx_rates_from_frankfurter
        for currency in missing:
            try:
                fetched = fetch_fn(
                    base_currency=base_currency,
                    quote_currencies=[currency],
                    as_of_date=as_of_date,
                )
            except Exception as exc:
                warnings.append(f"FX auto-ingest failed for {currency}: {exc}")
                continue
            fetched_rate = fetched.get(currency) if isinstance(fetched, dict) else None
            if not isinstance(fetched_rate, (int, float)) or fetched_rate <= 0:
                continue
            rate_value = float(fetched_rate)
            append_jsonl(
                fx_history_path,
                {
                    "as_of_date": as_of_date,
                    "base_currency": base_currency,
                    "quote_currency": currency,
                    "rate_to_base": rate_value,
                    "source": "frankfurter",
                    "ingested_at": _utc_now_iso(),
                },
            )
            rates_to_base[currency] = rate_value
            rate_dates[currency] = as_of_date
            sources[currency] = "auto_ingest"

    for currency in quote_currencies:
        if currency not in rates_to_base:
            warnings.append(
                f"Missing FX rate {currency}->{base_currency} as of {as_of_date}"
            )

    fx_lock = {
        "base_currency": base_currency,
        "snapshot_timestamp": snapshot_timestamp,
        "rates_to_base": {
            currency: rates_to_base[currency]
            for currency in quote_currencies
            if currency in rates_to_base
        },
        "rate_dates": {
            currency: rate_dates[currency]
            for currency in quote_currencies
            if currency in rate_dates
        },
        "sources": {
            currency: sources[currency]
            for currency in quote_currencies
            if currency in sources
        },
    }
    return fx_lock, warnings


def _fx_ref_from_lock(
    currency: str, fx_lock: dict[str, Any]
) -> dict[str, Any] | None:
    if not isinstance(fx_lock, dict):
        return None
    base_currency = _normalize_currency(fx_lock.get("base_currency"))
    quote = _normalize_currency(currency)
    if not base_currency or not quote or quote == base_currency:
        return None
    rates = fx_lock.get("rates_to_base") or {}
    rate = rates.get(quote) if isinstance(rates, dict) else None
    if not isinstance(rate, (int, float)) or rate <= 0:
        return None
    rate_dates = fx_lock.get("rate_dates") or {}
    sources = fx_lock.get("sources") or {}
    as_of_date = (
        rate_dates.get(quote) if isinstance(rate_dates, dict) else None
    )
    if not isinstance(as_of_date, str) or len(as_of_date) != 10:
        return None
    fx_ref: dict[str, Any] = {
        "as_of_date": as_of_date,
        "base_currency": base_currency,
        "quote_currency": quote,
        "rate_to_base": float(rate),
    }
    source = sources.get(quote) if isinstance(sources, dict) else None
    if isinstance(source, str) and source:
        fx_ref["source"] = source
    return fx_ref


def attach_fx_refs_to_holdings(
    portfolio: dict[str, Any], fx_lock: dict[str, Any]
) -> dict[str, Any]:
    """Return a deep copy of ``portfolio`` with fx_ref stamped on each
    foreign-currency ``holding.market_value`` and ``activity.money`` using
    the rates in ``fx_lock``.

    Idempotent: existing fx_ref values are preserved untouched. Money values
    whose currency equals the lock's base_currency or that lack a rate in
    the lock are left as-is.
    """
    new_portfolio = copy.deepcopy(portfolio) if isinstance(portfolio, dict) else {}
    if not isinstance(fx_lock, dict):
        return new_portfolio

    holdings = new_portfolio.get("holdings")
    if isinstance(holdings, list):
        for holding in holdings:
            if not isinstance(holding, dict):
                continue
            money = holding.get("market_value")
            if not isinstance(money, dict) or "fx_ref" in money:
                continue
            fx_ref = _fx_ref_from_lock(money.get("currency", ""), fx_lock)
            if fx_ref is not None:
                money["fx_ref"] = fx_ref

    activities = new_portfolio.get("activities")
    if isinstance(activities, list):
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            money = activity.get("money")
            if not isinstance(money, dict) or "fx_ref" in money:
                continue
            fx_ref = _fx_ref_from_lock(money.get("currency", ""), fx_lock)
            if fx_ref is not None:
                money["fx_ref"] = fx_ref

    return new_portfolio
