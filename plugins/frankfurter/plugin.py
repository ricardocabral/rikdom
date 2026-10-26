"""Explicit Frankfurter acquisition; core FX history and locks stay provider-neutral."""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rikdom.plugin_engine.errors import PluginEngineError
from rikdom.plugin_engine.hookspecs import hookimpl


_DESCRIPTION = {
    "contractVersion": "1.0",
    "readOnly": True,
    "provider": "frankfurter",
    "transport": "REST",
    "baseUrl": "https://api.frankfurter.app",
    "operations": {
        "daily-rates": {
            "path": "/{as_of_date}",
            "parameters": ["base_currency", "quote_currencies", "as_of_date"],
            "requiredParameters": ["base_currency", "quote_currencies", "as_of_date"],
            "result": "Currency-keyed rate_to_base, as_of_date, source objects",
        }
    },
}


class FrankfurterError(PluginEngineError):
    """A request or provider response cannot supply a trustworthy daily FX rate."""


def _currency(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value.strip()):
        raise FrankfurterError("Currencies must be three-letter codes")
    return value.strip().upper()


def _date(value) -> str:
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise FrankfurterError("FX dates must use a valid YYYY-MM-DD date")


class Plugin:
    @hookimpl
    def connector_describe(self, ctx):
        return copy.deepcopy(_DESCRIPTION)

    @hookimpl
    def connector_query(self, ctx, operation, params):
        if operation != "daily-rates":
            raise FrankfurterError("Unsupported Frankfurter operation; use daily-rates")
        required = {"base_currency", "quote_currencies", "as_of_date"}
        if not isinstance(params, dict) or set(params) != required:
            raise FrankfurterError("daily-rates requires base_currency, quote_currencies and as_of_date")
        base = _currency(params["base_currency"])
        requested_date = _date(params["as_of_date"])
        quotes = params["quote_currencies"]
        if not isinstance(quotes, list) or not quotes:
            raise FrankfurterError("quote_currencies must be a nonempty list")
        quotes = list(dict.fromkeys(_currency(quote) for quote in quotes))
        if base in quotes:
            raise FrankfurterError("quote_currencies must differ from base_currency")

        result = {}
        for quote in quotes:
            query = urlencode({"from": quote, "to": base})
            request = Request(
                f"https://api.frankfurter.app/{requested_date}?{query}",
                headers={"User-Agent": "rikdom-frankfurter/0.1.0", "Accept": "application/json"},
            )
            try:
                # Provider scheme/host are fixed; dates and currency codes are validated.
                with urlopen(request, timeout=10) as response:  # nosec B310
                    payload = json.loads(response.read())
            except HTTPError as error:
                status = error.code
                error.close()
                raise FrankfurterError(f"Frankfurter request failed: HTTP {status}") from None
            except (URLError, OSError, ValueError, UnicodeError):
                raise FrankfurterError("Frankfurter request failed; check connectivity and JSON response") from None
            if not isinstance(payload, dict):
                raise FrankfurterError("Frankfurter returned an invalid response")
            effective_date = _date(payload.get("date"))
            rates = payload.get("rates")
            rate = rates.get(base) if isinstance(rates, dict) else None
            amount = payload.get("amount")
            if (
                effective_date > requested_date
                or payload.get("base") != quote
                or isinstance(amount, bool)
                or amount != 1
                or not isinstance(rate, (int, float))
                or isinstance(rate, bool)
                or not math.isfinite(rate)
                or rate <= 0
            ):
                raise FrankfurterError("Frankfurter returned an invalid daily FX rate")
            result[quote] = {
                "rate_to_base": float(rate),
                "as_of_date": effective_date,
                "source": "frankfurter",
            }
        return result
