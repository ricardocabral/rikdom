"""BrAPI REST connector. Provider data stays outside Rikdom's portfolio model."""

from __future__ import annotations

import copy
import json
import os
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rikdom.plugin_engine.errors import PluginEngineError
from rikdom.plugin_engine.hookspecs import hookimpl


_HISTORY = ("range", "interval", "startDate", "endDate", "sortOrder", "includeRaw")
_OPERATIONS = {
    "quote": ("stocks/quote", ()),
    "historical": ("stocks/historical", _HISTORY),
    "dividends": (
        "stocks/dividends",
        ("startDate", "endDate", "sortBy", "sortOrder", "includeRaw"),
    ),
    "fii-indicators": ("fii/indicators", ()),
    "fii-historical": ("fii/historical", ("startDate", "endDate", "sortOrder")),
    "fii-dividends": ("fii/dividends", ("startDate", "endDate", "sortBy", "sortOrder")),
    "currency": ("currency", ()),
    "currency-historical": (
        "currency/historical",
        ("startDate", "endDate", "sortOrder", "limit"),
    ),
    "macro": ("macro", ("startDate", "endDate", "sortOrder", "limit")),
    "macro-latest": ("macro/latest", ()),
}
_LIMITED = {
    "fii-indicators",
    "fii-historical",
    "fii-dividends",
    "currency-historical",
    "macro",
    "macro-latest",
}
_DESCRIPTION = {
    "contractVersion": "1.0",
    "readOnly": True,
    "provider": "brapi",
    "transport": "REST",
    "baseUrl": "https://brapi.dev",
    "auth": {"environment": "BRAPI_TOKEN", "scheme": "Bearer"},
    "operations": {
        name: {
            "path": f"/api/v2/{path}",
            "parameters": ["symbols", *parameters],
            "requiredParameters": ["symbols"],
            "symbolParameter": "currency" if name.startswith("currency") else "symbols",
            "maxSymbols": 20 if name in _LIMITED else None,
        }
        for name, (path, parameters) in _OPERATIONS.items()
    },
}


class BrapiError(PluginEngineError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def _query(operation: str, symbols: list[str], parameters: dict) -> tuple[str, dict]:
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        raise BrapiError(
            "Unsupported BrAPI operation; use connector describe to list operations"
        )
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(s, str) for s in symbols)
    ):
        raise BrapiError(
            "symbols must be a nonempty list of strings or a comma-delimited string"
        )
    normalized = []
    for symbol in symbols:
        symbol = symbol.strip()
        if not symbol or not re.fullmatch(r"[A-Za-z0-9_.^-]+", symbol):
            raise BrapiError("symbols must contain nonempty provider identifiers")
        symbol = symbol.lower() if operation.startswith("macro") else symbol.upper()
        if symbol not in normalized:
            normalized.append(symbol)
    if operation in _LIMITED and len(normalized) > 20:
        raise BrapiError("This BrAPI operation accepts at most 20 symbols")
    path, allowed = _OPERATIONS[operation]
    if not isinstance(parameters, dict) or any(
        key not in allowed for key in parameters
    ):
        raise BrapiError(
            "Unsupported BrAPI parameter; use connector describe for allowed parameters"
        )
    query = {
        "currency" if operation.startswith("currency") else "symbols": ",".join(
            normalized
        )
    }
    for key, value in parameters.items():
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise BrapiError("BrAPI parameters must be strings or integers")
        if key != "limit" and not isinstance(value, str):
            raise BrapiError("BrAPI parameters other than limit must be strings")
        if key in ("startDate", "endDate"):
            try:
                date.fromisoformat(str(value))
            except ValueError:
                raise BrapiError("BrAPI dates must use YYYY-MM-DD") from None
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
                raise BrapiError("BrAPI dates must use YYYY-MM-DD")
        if key == "limit" and (not isinstance(value, int) or value <= 0):
            raise BrapiError("limit must be a positive integer")
        if key == "range" and value not in (
            "1d",
            "2d",
            "5d",
            "7d",
            "1mo",
            "3mo",
            "6mo",
            "1y",
            "2y",
            "5y",
            "10y",
            "ytd",
            "max",
        ):
            raise BrapiError("Unsupported BrAPI range")
        if key == "interval" and value not in (
            "1m",
            "2m",
            "5m",
            "15m",
            "30m",
            "60m",
            "90m",
            "1h",
            "1d",
            "5d",
            "1wk",
            "1mo",
            "3mo",
        ):
            raise BrapiError("Unsupported BrAPI interval")
        if key == "includeRaw" and value not in ("true", "false"):
            raise BrapiError("includeRaw must be true or false")
        if (
            key == "sortBy"
            and operation == "dividends"
            and value not in ("paymentDate", "lastDatePrior", "approvedOn", "rate")
        ):
            raise BrapiError("Unsupported BrAPI dividend sortBy")
        if key == "sortOrder" and value not in ("asc", "desc"):
            raise BrapiError("sortOrder must be asc or desc")
        query[key] = value
    if (
        "startDate" in query
        and "endDate" in query
        and query["startDate"] > query["endDate"]
    ):
        raise BrapiError("startDate must be on or before endDate")
    return path, query


def _retry_after(error: HTTPError) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    if not value:
        return None
    try:
        seconds = float(value)
        if not (0 <= seconds < float("inf")):
            return None
        return seconds
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


def fetch_brapi_data(
    operation: str, symbols: list[str], *, parameters: dict | None = None
) -> dict:
    path, query = _query(operation, symbols, {} if parameters is None else parameters)
    request = Request(
        f"https://brapi.dev/api/v2/{path}?{urlencode(query)}",
        headers={"Accept": "application/json", "User-Agent": "rikdom-brapi/0.1.0"},
    )
    token = os.environ.get("BRAPI_TOKEN", "").strip()
    if token:
        if "\r" in token or "\n" in token:
            raise BrapiError("BRAPI_TOKEN contains invalid header characters")
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    for attempt in range(3):
        try:
            with urlopen(request, timeout=10) as response:  # nosec B310: fixed HTTPS provider endpoint
                payload = json.loads(response.read())
        except HTTPError as error:
            delay = _retry_after(error) if error.code == 429 else None
            error.close()
            if error.code == 429 and attempt < 2:
                wait = delay if delay is not None else 2**attempt
                if wait <= 60:
                    time.sleep(wait)
                    continue
            messages = {
                401: "BrAPI authentication failed; set a valid BRAPI_TOKEN from https://brapi.dev/dashboard or use a public demo symbol",
                403: "BrAPI access denied; check the token's plan and permissions at https://brapi.dev/pricing",
                404: "BrAPI resource not found; check the operation and symbols",
                429: "BrAPI rate limit reached; retry later or check your plan",
            }
            message = (
                f"HTTP {error.code}: {messages.get(error.code, 'BrAPI request failed')}"
            )
            if delay is not None:
                message += f"; retry after {delay:g} seconds"
            raise BrapiError(
                message, status_code=error.code, retry_after=delay
            ) from None
        except (URLError, OSError, ValueError, UnicodeError):
            raise BrapiError(
                "BrAPI request failed; check connectivity and the provider's JSON response"
            ) from None
        if not isinstance(payload, dict):
            raise BrapiError(
                "BrAPI returned an invalid response; expected a JSON object"
            )
        return payload
    raise BrapiError("BrAPI rate limit reached", status_code=429)  # pragma: no cover


class Plugin:
    @hookimpl
    def connector_describe(self, ctx):
        return copy.deepcopy(_DESCRIPTION)

    @hookimpl
    def connector_query(self, ctx, operation, params):
        if not isinstance(params, dict):
            raise BrapiError("BrAPI query params must be an object")
        symbols = params.get("symbols", [])
        if isinstance(symbols, str):
            symbols = symbols.split(",")
        parameters = {key: value for key, value in params.items() if key != "symbols"}
        return fetch_brapi_data(operation, symbols, parameters=parameters)
