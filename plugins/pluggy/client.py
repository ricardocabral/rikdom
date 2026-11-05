"""Read-only Pluggy transport. Credentials and API keys remain in memory."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from rikdom.plugin_engine.errors import PluginEngineError

_BASE = "https://api.pluggy.ai"
_CREDENTIALS = ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET")


class PluggyError(PluginEngineError):
    """A safe transport or completeness error without provider response details."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Pluggy endpoints are fixed; no redirect is needed, including same-host ones.
        raise PluggyError("Pluggy redirect refused")


def _credentials(env_file: str | Path | None) -> tuple[str, str]:
    values = {}
    if env_file is not None and not isinstance(env_file, (str, Path)):
        raise PluggyError("Pluggy credentials file must be a path")
    if env_file is not None:
        try:
            lines = Path(env_file).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            raise PluggyError("Cannot read Pluggy credentials file") from None
        for line in lines:
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            key, sep, value = line.partition("=")
            key = key.strip()
            if sep and key in _CREDENTIALS:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                values[key] = value
    result = tuple(os.environ.get(key, values.get(key, "")) for key in _CREDENTIALS)
    if not all(result):
        raise PluggyError("Set PLUGGY_CLIENT_ID and PLUGGY_CLIENT_SECRET")
    return result


def _timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result
    except (ValueError, AttributeError, TypeError):
        raise PluggyError("Invalid Pluggy timestamp") from None


def validate_item(
    item: dict,
    *,
    as_of: str,
    include_transactions: bool = True,
    include_bank_accounts: bool = True,
) -> None:
    """Reject snapshots whose requested products are incomplete or unauthorized."""
    if (
        not isinstance(item, dict)
        or item.get("status") != "UPDATED"
        or item.get("executionStatus") != "SUCCESS"
    ):
        raise PluggyError(
            "Pluggy item is not fully updated; complete synchronization in MeuPluggy"
        )
    if (
        item.get("error")
        or item.get("userAction")
        or item.get("hasResourcesPendingAuthorization")
    ):
        raise PluggyError(
            "Pluggy item requires attention or authorization in MeuPluggy"
        )
    now = _timestamp(as_of)
    expires = item.get("consentExpiresAt")
    if expires is not None and _timestamp(expires) <= now:
        raise PluggyError("Pluggy consent expired; renew authorization in MeuPluggy")
    detail = item.get("statusDetail")
    if detail is None:
        return
    if not isinstance(detail, dict):
        raise PluggyError("Invalid Pluggy product status")
    products = ["investments"]
    if include_bank_accounts:
        products.append("accounts")
    if include_transactions:
        products.append("investmentsTransactions")
    for product in products:
        status = detail.get(product)
        if status is not None and (
            not isinstance(status, dict)
            or status.get("isUpdated") is not True
            or status.get("warnings")
        ):
            raise PluggyError("Pluggy requested product is incomplete or has warnings")


def _request(
    opener, path: str, *, api_key: str | None = None, data: dict | None = None
) -> dict:
    headers = {"Accept": "application/json"}
    if api_key is not None:
        headers["X-API-KEY"] = api_key
    encoded = None
    if data is not None:
        encoded = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(_BASE + path, data=encoded, headers=headers)
    for attempt in range(3):
        try:
            with opener.open(request, timeout=30) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise PluggyError("Invalid Pluggy JSON response")
            return result
        except HTTPError as error:
            code = error.code
            error.close()
            if (code == 429 or 500 <= code <= 599) and attempt < 2:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise PluggyError(f"Pluggy request failed (HTTP {code})") from None
        except (URLError, OSError, TimeoutError):
            raise PluggyError("Pluggy request failed; check connectivity") from None
        except (ValueError, UnicodeError):
            raise PluggyError("Invalid Pluggy JSON response") from None
    raise PluggyError("Pluggy request failed")


def _pages(opener, path: str, api_key: str, query: dict | None = None) -> list[dict]:
    unique = {}
    expected = None
    number = 1
    while True:
        payload = _request(
            opener,
            path + "?" + urlencode({**(query or {}), "page": number, "pageSize": 500}),
            api_key=api_key,
        )
        metadata = tuple(payload.get(key) for key in ("total", "totalPages"))
        total, pages = metadata
        if (
            any(type(value) is not int or value < 0 for value in metadata)
            or pages > 10000
            or type(payload.get("page")) is not int
            or payload.get("page") != number
            or not isinstance(payload.get("results"), list)
            or (expected is not None and metadata != expected)
            or (total > 0 and pages == 0)
            or (total == 0 and pages > 1)
        ):
            raise PluggyError("Invalid or inconsistent Pluggy pagination")
        expected = metadata
        rows = payload["results"]
        if not rows and total:
            raise PluggyError("Missing Pluggy result page")
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not row["id"]
            ):
                raise PluggyError("Pluggy result is missing an identifier")
            identifier = row["id"]
            if identifier in unique and unique[identifier] != row:
                raise PluggyError("Conflicting duplicate Pluggy result")
            unique[identifier] = row
        if number >= pages:
            if total != len(unique):
                raise PluggyError("Pluggy result count does not match pagination")
            return list(unique.values())
        number += 1


def fetch_portfolio(
    item_ids: list[str],
    *,
    include_transactions: bool = True,
    include_bank_accounts: bool = True,
    env_file: str | Path | None = None,
) -> dict:
    """Fetch a complete raw portfolio for explicitly supplied MeuPluggy item IDs."""
    if not isinstance(item_ids, list) or not item_ids:
        raise PluggyError("Supply a nonempty list of Pluggy item UUIDs")
    normalized = []
    for identifier in item_ids:
        try:
            if not isinstance(identifier, str):
                raise ValueError
            canonical = str(UUID(identifier))
            if identifier.lower() != canonical:
                raise ValueError
        except (ValueError, AttributeError):
            raise PluggyError("Pluggy item IDs must be UUIDs") from None
        if canonical not in normalized:
            normalized.append(canonical)
    if (
        type(include_transactions) is not bool
        or type(include_bank_accounts) is not bool
    ):
        raise PluggyError("Pluggy inclusion options must be booleans")
    client_id, secret = _credentials(env_file)
    opener = build_opener(_NoRedirect())
    auth = _request(
        opener, "/auth", data={"clientId": client_id, "clientSecret": secret}
    )
    api_key = auth.get("apiKey")
    if not isinstance(api_key, str) or not api_key:
        raise PluggyError("Pluggy authentication did not return an API key")
    fetched_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "format": "pluggy-portfolio-v1",
        "fetched_at": fetched_at,
        "include_transactions": include_transactions,
        "include_bank_accounts": include_bank_accounts,
        "items": [],
    }
    for identifier in normalized:
        item = _request(opener, "/items/" + identifier, api_key=api_key)
        if item.get("id") != identifier:
            raise PluggyError("Pluggy item ownership mismatch")
        validate_item(
            item,
            as_of=fetched_at,
            include_transactions=include_transactions,
            include_bank_accounts=include_bank_accounts,
        )
        accounts = (
            _pages(opener, "/accounts", api_key, {"itemId": identifier, "type": "BANK"})
            if include_bank_accounts
            else []
        )
        if any(account.get("itemId") != identifier for account in accounts):
            raise PluggyError("Pluggy result item ownership mismatch")
        if any(account.get("type") != "BANK" for account in accounts):
            raise PluggyError("Pluggy returned an unexpected account type")
        investments = _pages(opener, "/investments", api_key, {"itemId": identifier})
        if any(investment.get("itemId") != identifier for investment in investments):
            raise PluggyError("Pluggy result item ownership mismatch")
        transactions = {}
        if include_transactions:
            for investment in investments:
                investment_id = investment["id"]
                rows = _pages(
                    opener,
                    "/investments/" + quote(investment_id, safe="") + "/transactions",
                    api_key,
                )
                if any(
                    row.get("investmentId", investment_id) != investment_id
                    or row.get("itemId", identifier) != identifier
                    for row in rows
                ):
                    raise PluggyError("Pluggy transaction ownership mismatch")
                transactions[investment_id] = rows
        snapshot["items"].append(
            {
                "item": item,
                "accounts": accounts,
                "investments": investments,
                "investment_transactions": transactions,
            }
        )
    return snapshot
