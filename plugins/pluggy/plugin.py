"""Meu Pluggy acquisition and offline import; portfolio writes stay in Rikdom.

Provider IDs identify records, not economic similarity. Reviewed mappings bind
positions to existing holdings/accounts; absent rows never establish a closure.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import re
import sys
from datetime import timezone
from pathlib import Path
from typing import Any

from rikdom.import_normalization import (
    normalize_currency,
    normalize_datetime,
    with_import_diagnostics,
)
from rikdom.plugin_engine.hookspecs import hookimpl


def _load_client():
    spec = importlib.util.spec_from_file_location(
        f"{__name__}_client", Path(__file__).with_name("client.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


client = _load_client()

_ASSET_TYPES = [
    {"id": "pluggy_stock", "label": "Pluggy stock or BDR", "asset_class": "stocks"},
    {"id": "pluggy_fii", "label": "Pluggy real estate fund", "asset_class": "reits"},
    {"id": "pluggy_fund", "label": "Pluggy fund or ETF", "asset_class": "funds"},
    {
        "id": "pluggy_fixed_income",
        "label": "Pluggy fixed income",
        "asset_class": "debt",
    },
    {
        "id": "pluggy_cash",
        "label": "Pluggy bank cash",
        "asset_class": "cash_equivalents",
    },
    {
        "id": "pluggy_retirement",
        "label": "Pluggy retirement (exposure unclassified)",
        "asset_class": "other",
    },
    {
        "id": "pluggy_structured_note",
        "label": "Pluggy structured note (exposure unclassified)",
        "asset_class": "other",
    },
    {
        "id": "pluggy_other",
        "label": "Pluggy unclassified investment",
        "asset_class": "other",
    },
]
_DESCRIPTION = {
    "contractVersion": "1.0",
    "readOnly": True,
    "provider": "pluggy",
    "transport": "REST",
    "baseUrl": "https://api.pluggy.ai",
    "auth": {
        "environment": ["PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET"],
        "envFile": "explicit env_file parameter only",
    },
    "operations": {
        "portfolio": {
            "description": "Read selected Meu Pluggy items, bank cash, investments and investment transactions; no portfolio writes or forced sync",
            "parameters": [
                "item_ids",
                "include_transactions",
                "include_bank_accounts",
                "env_file",
            ],
            "requiredParameters": ["item_ids"],
        }
    },
}
_FEE_FIELDS = {
    "serviceTax",
    "brokerageFee",
    "tradingAssetsNoticeFee",
    "maintenanceFee",
    "settlementFee",
    "clearingFee",
    "stockExchangeFee",
    "custodyFee",
    "operatingFee",
}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Pluggy {field} must be a nonempty string")
    return value.strip()


def _number(
    value: Any, field: str, *, optional: bool = False, nonnegative: bool = False
) -> float | None:
    if value is None and optional:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"Pluggy {field} must be a finite JSON number")
    if nonnegative and value < 0:
        raise ValueError(f"Pluggy {field} must be nonnegative")
    return value


def _time(value: Any, field: str) -> str:
    # Pluggy also supplies calendar dates. Preserve the API date at UTC midnight.
    result = normalize_datetime(value, naive_timezone=timezone.utc)
    if result is None:
        raise ValueError(f"Pluggy {field} must be an ISO date or timestamp")
    return result


def _currency(row: dict) -> str:
    value = normalize_currency(row.get("currencyCode"))
    if value is None:
        raise ValueError("Pluggy currencyCode must be a three-letter currency")
    return value


def _money(amount: float, currency: str) -> dict:
    return {"amount": amount, "currency": currency}


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _rows(value: Any, field: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Pluggy {field} must be an array of objects")
    return value


def _unique(rows: list[dict], field: str) -> list[dict]:
    seen = {}
    for row in rows:
        key = _text(row.get("id"), f"{field} id")
        if key in seen and seen[key] != row:
            raise ValueError(f"Pluggy conflicting duplicate {field} id")
        seen[key] = row
    return list(seen.values())


def _mappings(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - {
        "items",
        "investments",
        "accounts",
        "transactions",
    }:
        raise ValueError(
            "Pluggy mappings supports items, investments, accounts and transactions"
        )
    for group, entries in value.items():
        if not isinstance(entries, dict):
            raise ValueError(f"Pluggy mappings.{group} must be an object")
        for key, entry in entries.items():
            _text(key, "mapping source id")
            allowed = (
                {"account_id"}
                if group == "items"
                else {
                    "holding_id",
                    "account_id",
                    "asset_type_id",
                    "canonical_key",
                    "skip",
                }
            )
            if group == "transactions":
                allowed = {"event_type", "skip"}
            if not isinstance(entry, dict) or set(entry) - allowed:
                raise ValueError(f"Invalid Pluggy {group} mapping")
            for name, item in entry.items():
                if name == "skip":
                    if not isinstance(item, bool):
                        raise ValueError("Pluggy mapping skip must be boolean")
                elif name in ("account_id", "asset_type_id"):
                    if not isinstance(item, str) or not re.fullmatch(
                        r"[a-z0-9_-]+", item
                    ):
                        raise ValueError(f"Invalid Pluggy mapping {name}")
                elif name == "event_type":
                    if item not in ("income", "dividend", "interest"):
                        raise ValueError(
                            "Pluggy income mapping must be income, dividend or interest"
                        )
                else:
                    _text(item, f"mapping {name}")
    return value


def _mapping(mappings: dict, kind: str, row: dict, item_id: str) -> dict:
    result = dict(mappings.get("items", {}).get(item_id, {}))
    result.update(mappings.get(kind, {}).get(row["id"], {}))
    return result


def _diagnostic(
    scope: str, row: dict, reason: str, *, source_event: str | None = None
) -> dict:
    return {
        "scope": scope,
        "source_ref": f"{scope}:{row.get('id', 'unidentified')}",
        "source_event": source_event
        or str(row.get("type") or row.get("status") or "position"),
        "reason": reason,
        "affects_quantity": True,
        "affects_cash": True,
        "metadata": {"pluggy": copy.deepcopy(row)},
    }


def _asset_type(row: dict) -> str:
    if row.get("subtype") == "REAL_ESTATE_FUND":
        return "pluggy_fii"
    return {
        "EQUITY": "pluggy_stock",
        "ETF": "pluggy_fund",
        "MUTUAL_FUND": "pluggy_fund",
        "FIXED_INCOME": "pluggy_fixed_income",
        "SECURITY": "pluggy_retirement",
        "COE": "pluggy_structured_note",
    }.get(row.get("type"), "pluggy_other")


def _holding(row: dict, item: dict, mapping: dict, *, bank: bool = False) -> dict:
    currency = _currency(row)
    amount = _number(
        row.get("balance") if bank else row.get("amount"),
        "balance" if bank else "amount",
    )
    as_of = _time(
        (row.get("updatedAt") or item.get("lastUpdatedAt"))
        if bank
        else row.get("date"),
        "valuation date",
    )
    kind = "account" if bank else "investment"
    holding = {
        "id": mapping.get("holding_id") or f"pluggy:{kind}:{row['id']}",
        "asset_type_id": mapping.get("asset_type_id")
        or ("pluggy_cash" if bank else _asset_type(row)),
        "label": _text(row.get("name"), "name"),
        "market_value": _money(amount, currency),
        "as_of": as_of,
        "identifiers": {"provider_account_id": row["id"] if bank else item["id"]},
        "metadata": {
            "pluggy": copy.deepcopy(row),
            "pluggy_item_id": item["id"],
            "pluggy_record_type": kind,
        },
        "provenance": {
            "source_system": "pluggy",
            "source_ref": f"{kind}:{row['id']}",
            "idempotency_key": f"pluggy:{kind}:{row['id']}",
        },
    }
    for field in ("account_id",):
        if field in mapping:
            holding[field] = mapping[field]
    if "canonical_key" in mapping:
        holding["metadata"]["canonical_key"] = mapping["canonical_key"]
    if bank:
        # Account balances are monetary observations, not a quantity of securities.
        holding["quantity"] = None
        return holding
    holding["quantity"] = _number(
        row.get("quantity"), "quantity", optional=True, nonnegative=True
    )
    code = row.get("code")
    if code and row.get("type") in ("EQUITY", "ETF"):
        holding["identifiers"]["ticker"] = _text(code, "code")
    if row.get("isin"):
        holding["identifiers"]["isin"] = _text(row["isin"], "isin")
    holding["valuation"] = {"price_as_of": as_of}
    for field, target in (("balance", "net_value"), ("value", "unit_price")):
        value = _number(row.get(field), field, optional=True)
        if value is not None:
            holding["valuation"][target] = _money(value, currency)
    provisions = []
    for field, tax_type in (("taxes", "IR"), ("taxes2", "IOF")):
        value = _number(row.get(field), field, optional=True, nonnegative=True)
        if value is not None:
            provisions.append({"tax_type": tax_type, "money": _money(value, currency)})
    if provisions:
        holding["valuation"]["tax_provisions"] = provisions
    return holding


def _activity(
    row: dict, holding: dict, scope: str, mapping: dict, unsupported: list
) -> dict | None:
    raw_type = row.get("type")
    direction = row.get("movementType")
    event_type = {
        "BUY": "buy",
        "SELL": "sell",
        "TAX": "tax_withheld",
        "INTEREST": "income",
        "AMORTIZATION": "amortization",
    }.get(raw_type)
    if raw_type == "TRANSFER" and direction in ("CREDIT", "DEBIT"):
        event_type = "transfer_in" if direction == "CREDIT" else "transfer_out"
    if mapping.get("skip"):
        unsupported.append(
            _diagnostic(scope, row, "User excluded movement for overlap review")
        )
        return None
    if not row.get("id") or not event_type:
        unsupported.append(
            _diagnostic(
                scope,
                row,
                "Missing source transaction id or unsupported movement type/direction",
            )
        )
        return None
    if (raw_type == "BUY" and direction not in (None, "CREDIT")) or (
        raw_type in ("SELL", "INTEREST", "TAX", "AMORTIZATION")
        and direction not in (None, "DEBIT")
    ):
        unsupported.append(
            _diagnostic(
                scope, row, "Reversed or unexpected movement direction requires review"
            )
        )
        return None
    amount = _number(
        row.get("amount"),
        "transaction amount",
        optional=raw_type == "TRANSFER",
        nonnegative=True,
    )
    currency = holding["market_value"]["currency"]
    source_id = _text(row["id"], "transaction id")
    activity = {
        "id": f"pluggy:transaction:{source_id}",
        "idempotency_key": f"pluggy:transaction:{source_id}",
        "source_system": "pluggy",
        "source_ref": f"investment-transaction:{source_id}",
        "event_type": event_type,
        "status": "posted",
        "effective_at": _time(row.get("date"), "transaction date"),
        "asset_type_id": holding["asset_type_id"],
        "metadata": {
            "pluggy": copy.deepcopy(row),
            "rikdom_source_identity": {
                "version": 1,
                "scope": scope,
                "kind": "source",
                "occurrence": 0,
                "document_fingerprint": _fingerprint(row),
                "signature": source_id,
            },
        },
    }
    if holding.get("id"):
        activity["holding_id"] = holding["id"]
    if holding.get("identifiers"):
        activity["instrument"] = copy.deepcopy(holding["identifiers"])
    if "account_id" in holding:
        activity["account_id"] = holding["account_id"]
    if amount is not None:
        activity["money"] = _money(amount, currency)
    if row.get("tradeDate") is not None:
        # Despite its name, Pluggy documents tradeDate as the settlement date.
        activity["settled_at"] = _time(row["tradeDate"], "tradeDate")
    quantity = _number(
        row.get("quantity"), "transaction quantity", optional=True, nonnegative=True
    )
    if quantity is not None and event_type in (
        "buy",
        "sell",
        "transfer_in",
        "transfer_out",
    ):
        activity["quantity"] = quantity
    expenses = row.get("expenses")
    if expenses is not None:
        if not isinstance(expenses, dict):
            raise ValueError("Pluggy transaction expenses must be an object")
        fees, taxes = [], []
        for field, value in expenses.items():
            value = _number(value, f"expenses.{field}", optional=True, nonnegative=True)
            if value is None:
                continue
            if field in _FEE_FIELDS:
                fees.append(value)
            elif field in ("incomeTax", "iof", "other"):
                taxes.append(value)
        if fees:
            activity["fees"] = _money(sum(fees), currency)
        if taxes and raw_type != "TAX":
            activity["withholding_tax"] = _money(sum(taxes), currency)
    if raw_type == "INTEREST":
        activity["event_type"] = mapping.get("event_type", "income")
        activity["metadata"]["rikdom_income"] = {"version": 1, "amount_basis": "gross"}
    elif "event_type" in mapping:
        raise ValueError("Pluggy event_type mapping applies only to INTEREST movements")
    return activity


def normalize_snapshot(snapshot: dict, mappings: dict | None = None) -> dict:
    """Normalize a complete saved acquisition, independently of portfolio state."""
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("format") != "pluggy-portfolio-v1"
    ):
        raise ValueError("Expected a pluggy-portfolio-v1 acquisition snapshot")
    fetched_at = _time(snapshot.get("fetched_at"), "fetched_at")
    mappings = _mappings({} if mappings is None else mappings)
    for option in ("include_transactions", "include_bank_accounts"):
        if not isinstance(snapshot.get(option), bool):
            raise ValueError(f"Pluggy snapshot requires boolean {option}")
    holdings, activities, unsupported, coverage = [], [], [], []
    source_holdings, source_activities, mapped_holdings, seen_items = {}, {}, {}, set()
    for bundle in _rows(snapshot.get("items"), "items"):
        item = bundle.get("item")
        if not isinstance(item, dict):
            raise ValueError("Pluggy item must be an object")
        client.validate_item(
            item,
            as_of=fetched_at,
            include_transactions=snapshot["include_transactions"],
            include_bank_accounts=snapshot["include_bank_accounts"],
        )
        item_id = _text(item.get("id"), "item id")
        if item_id in seen_items:
            raise ValueError("Pluggy duplicate item in acquisition snapshot")
        seen_items.add(item_id)
        scope = f"pluggy:item:{item_id}"
        start_activities = len(activities)
        if not isinstance(bundle.get("investment_transactions"), dict):
            raise ValueError("Pluggy investment_transactions must be an object")
        investments = _unique(
            _rows(bundle.get("investments"), "investments"), "investments"
        )
        expected_transactions = (
            {row["id"] for row in investments}
            if snapshot["include_transactions"]
            else set()
        )
        if set(bundle["investment_transactions"]) != expected_transactions:
            raise ValueError(
                "Pluggy snapshot is missing or has unexpected investment transactions"
            )
        for kind in ("accounts", "investments"):
            rows = (
                investments
                if kind == "investments"
                else _unique(_rows(bundle.get(kind), kind), kind)
            )
            if kind == "accounts" and not snapshot["include_bank_accounts"] and rows:
                raise ValueError(
                    "Pluggy snapshot contains accounts outside acquisition scope"
                )
            for row in rows:
                if row.get("itemId") != item_id:
                    raise ValueError("Pluggy record belongs to a different item")
                bank = kind == "accounts"
                mapping = _mapping(mappings, kind, row, item_id)
                if mapping.get("skip"):
                    unsupported.append(
                        _diagnostic(
                            scope,
                            row,
                            "User excluded position to avoid an overlapping source",
                        )
                    )
                    continue
                if bank and row.get("type") != "BANK":
                    raise ValueError("Pluggy portfolio cash requires BANK accounts")
                has_valuation = True
                if not bank:
                    status = row.get("status")
                    if status not in (None, "ACTIVE", "TOTAL_WITHDRAWAL"):
                        unsupported.append(
                            _diagnostic(
                                scope,
                                row,
                                "Pending or unknown position status does not establish settled holdings",
                            )
                        )
                        continue
                    if status == "TOTAL_WITHDRAWAL" and (
                        row.get("balance") != 0
                        or row.get("amount") not in (None, 0)
                        or row.get("quantity") not in (None, 0)
                    ):
                        finding = _diagnostic(
                            scope,
                            row,
                            "Closed position has inconsistent nonzero values; review before changing the stored position",
                        )
                        finding["metadata"]["investment_transactions"] = copy.deepcopy(
                            bundle["investment_transactions"].get(row["id"], [])
                        )
                        unsupported.append(finding)
                        has_valuation = False
                    elif status == "TOTAL_WITHDRAWAL":
                        row = {**row, "amount": 0, "quantity": 0}
                    if row.get("amount") is None:
                        unsupported.append(
                            _diagnostic(
                                scope,
                                row,
                                "Gross position amount unavailable; net balance is not a gross valuation",
                            )
                        )
                        has_valuation = False
                if has_valuation:
                    holding = _holding(row, item, mapping, bank=bank)
                else:
                    # Known movements remain useful even without a current valuation.
                    # Only an explicit mapping can bind these to an existing holding.
                    holding = {
                        "asset_type_id": mapping.get("asset_type_id")
                        or _asset_type(row),
                        "market_value": {"currency": _currency(row)},
                        "identifiers": {},
                    }
                    if row.get("code") and row.get("type") in ("EQUITY", "ETF"):
                        holding["identifiers"]["ticker"] = _text(row["code"], "code")
                    if row.get("isin"):
                        holding["identifiers"]["isin"] = _text(row["isin"], "isin")
                    if mapping.get("holding_id"):
                        holding["id"] = mapping["holding_id"]
                    if mapping.get("account_id"):
                        holding["account_id"] = mapping["account_id"]
                source_key = (kind, row["id"])
                if source_key in source_holdings:
                    if source_holdings[source_key] != holding:
                        raise ValueError(
                            "Pluggy conflicting duplicate position across items"
                        )
                    continue
                if has_valuation and holding["id"] in mapped_holdings:
                    raise ValueError(
                        "Pluggy holding mappings must not map distinct positions to the same holding"
                    )
                source_holdings[source_key] = holding
                if has_valuation:
                    mapped_holdings[holding["id"]] = source_key
                    holdings.append(holding)
                if bank or not snapshot["include_transactions"]:
                    continue
                txs = bundle["investment_transactions"].get(row["id"])
                if txs is None:
                    raise ValueError(
                        "Pluggy snapshot is missing investment transactions; refetch the complete acquisition"
                    )
                identified, unidentified = [], []
                for tx in _rows(txs, "investment transactions"):
                    if (
                        tx.get("investmentId", row["id"]) != row["id"]
                        or tx.get("itemId", item_id) != item_id
                    ):
                        raise ValueError(
                            "Pluggy transaction ownership refers to a different investment or item"
                        )
                    (identified if tx.get("id") else unidentified).append(tx)
                for tx in [*_unique(identified, "transactions"), *unidentified]:
                    transaction_mapping = mappings.get("transactions", {}).get(
                        tx.get("id"), {}
                    )
                    activity = _activity(
                        tx,
                        holding,
                        f"pluggy:investment:{row['id']}",
                        transaction_mapping,
                        unsupported,
                    )
                    if activity is None:
                        continue
                    previous = source_activities.get(activity["id"])
                    if previous is not None:
                        if previous != activity:
                            raise ValueError(
                                "Pluggy conflicting duplicate transaction id across investments"
                            )
                        continue
                    source_activities[activity["id"]] = activity
                    activities.append(activity)
        coverage.append(
            {
                "scope": scope,
                "status": "partial" if snapshot["include_transactions"] else "unknown",
                "event_types": sorted(
                    {a["event_type"] for a in activities[start_activities:]}
                ),
                "reasons": [
                    "Available API history is not proven complete from inception; absent positions are not closed"
                ],
            }
        )
    if not coverage:
        raise ValueError("Pluggy acquisition must contain at least one selected item")
    return with_import_diagnostics(
        {
            "provider": "pluggy",
            "generated_at": fetched_at,
            "holdings": holdings,
            "activities": activities,
        },
        history_coverage=coverage,
        unsupported_events=unsupported,
    )


class Plugin:
    @hookimpl
    def connector_describe(self, ctx):
        return copy.deepcopy(_DESCRIPTION)

    @hookimpl
    def connector_query(self, ctx, operation, params):
        if (
            operation != "portfolio"
            or not isinstance(params, dict)
            or set(params)
            - {"item_ids", "include_transactions", "include_bank_accounts", "env_file"}
        ):
            raise ValueError(
                "Pluggy supports portfolio with item_ids and optional include_transactions, include_bank_accounts, env_file"
            )
        return client.fetch_portfolio(
            params.get("item_ids"),
            **{k: v for k, v in params.items() if k != "item_ids"},
        )

    @hookimpl
    def source_input(self, ctx, input_path):
        path = Path(input_path)
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("Pluggy import input must be a JSON object")
        mappings = document.get("mappings", {})
        if "snapshot" in document:
            if set(document) - {"snapshot", "mappings"}:
                raise ValueError(
                    "Pluggy import configuration supports snapshot and mappings only"
                )
            source = Path(_text(document["snapshot"], "snapshot path"))
            source = source if source.is_absolute() else path.parent / source
            document = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(document, dict) and "data" in document:
            if (
                document.get("plugin", {}).get("name") != "pluggy"
                or document.get("operation") != "portfolio"
            ):
                raise ValueError("Expected a Pluggy portfolio connector envelope")
            document = document["data"]
        return normalize_snapshot(document, mappings)

    @hookimpl
    def asset_type_catalog(self, ctx):
        return copy.deepcopy(_ASSET_TYPES)
