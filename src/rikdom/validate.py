from __future__ import annotations

import re
from datetime import datetime
from typing import Any


CORE_TOP_LEVEL = {
    "schema_version",
    "schema_uri",
    "profile",
    "settings",
    "asset_type_catalog",
    "holdings",
}


VALID_INSTRUMENT_VALUE_TYPES = {"string", "integer", "number", "boolean"}


CANONICAL_SCHEMA_URI = "https://example.org/rikdom/schema/portfolio.schema.json"
CURRENT_SCHEMA_VERSION = (1, 7, 0)
MIN_COMPATIBLE_SCHEMA_VERSION = (1, 0, 0)


LIABILITY_KINDS = {
    "mortgage",
    "secured_loan",
    "unsecured_loan",
    "student_loan",
    "margin",
    "credit_line",
    "credit_card",
    "tax",
    "other",
}

TAX_LOT_ACQUISITION_KINDS = {
    "buy",
    "transfer_in",
    "dividend_reinvest",
    "split",
    "grant_vest",
    "gift",
    "inheritance",
    "other",
}

ACTIVITY_EVENT_TYPES = {
    "amortization",
    "buy",
    "sell",
    "dividend",
    "interest",
    "fee",
    "transfer_in",
    "transfer_out",
    "split",
    "merger",
    "income",
    "reimbursement",
    "contribution",
    "withdrawal",
    "tax_withheld",
    "fx_conversion",
    "other",
}

_ACCOUNT_ID_RE = re.compile(r"^[a-z0-9_\-]+$")

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.match(value)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _is_iso_datetime(value: str) -> bool:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


def _validate_iso_datetime_field(
    value: Any,
    path: str,
    errors: list[str],
    *,
    required: bool = False,
) -> None:
    if value is None or value == "":
        if required:
            errors.append(f"{path} is required")
        return
    if not isinstance(value, str) or not _is_iso_datetime(value):
        errors.append(f"{path} must be an ISO-8601 datetime string")


def _check_schema_compatibility(portfolio: dict[str, Any], errors: list[str]) -> None:
    raw_version = portfolio.get("schema_version")
    if raw_version is None:
        return
    if not isinstance(raw_version, str):
        errors.append("'schema_version' must be a string")
        return

    parsed = _parse_semver(raw_version)
    if parsed is None:
        errors.append(
            f"'schema_version' '{raw_version}' must be semantic version MAJOR.MINOR.PATCH"
        )
        return

    current_major = CURRENT_SCHEMA_VERSION[0]
    if parsed[0] != current_major and parsed != (2, 0, 0):
        errors.append(
            f"schema_version '{raw_version}' is incompatible: "
            f"reader supports major {current_major}.x "
            f"(minimum {'.'.join(str(p) for p in MIN_COMPATIBLE_SCHEMA_VERSION)}, "
            f"current {'.'.join(str(p) for p in CURRENT_SCHEMA_VERSION)})"
        )
        return

    if parsed < MIN_COMPATIBLE_SCHEMA_VERSION:
        errors.append(
            f"schema_version '{raw_version}' is below minimum compatible "
            f"{'.'.join(str(p) for p in MIN_COMPATIBLE_SCHEMA_VERSION)}"
        )
        return

    if parsed > CURRENT_SCHEMA_VERSION and parsed != (2, 0, 0):
        errors.append(
            f"schema_version '{raw_version}' is newer than current "
            f"{'.'.join(str(p) for p in CURRENT_SCHEMA_VERSION)}; "
            "reader may not understand all fields"
        )

    schema_uri = portfolio.get("schema_uri")
    if isinstance(schema_uri, str) and schema_uri != CANONICAL_SCHEMA_URI:
        errors.append(
            f"schema_uri '{schema_uri}' does not match canonical '{CANONICAL_SCHEMA_URI}'"
        )


def _is_typed_value(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return False


def _collect_instrument_attribute_defs(
    asset_type: dict[str, Any],
    asset_type_index: int,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    attrs = asset_type.get("instrument_attributes")
    if attrs is None:
        return {}
    if not isinstance(attrs, list):
        errors.append(
            f"asset_type_catalog[{asset_type_index}].instrument_attributes must be an array"
        )
        return {}

    defs_by_id: dict[str, dict[str, Any]] = {}
    for j, item in enumerate(attrs):
        prefix = f"asset_type_catalog[{asset_type_index}].instrument_attributes[{j}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue

        attr_id = str(item.get("id", "")).strip()
        if not attr_id:
            errors.append(f"{prefix}.id is required")
            continue
        if attr_id in defs_by_id:
            errors.append(
                f"Duplicate instrument attribute id '{attr_id}' in asset_type_catalog[{asset_type_index}]"
            )
            continue

        label = str(item.get("label", "")).strip()
        if not label:
            errors.append(f"{prefix}.label is required")

        value_type = str(item.get("value_type", "")).strip()
        if value_type not in VALID_INSTRUMENT_VALUE_TYPES:
            errors.append(
                f"{prefix}.value_type must be one of: {', '.join(sorted(VALID_INSTRUMENT_VALUE_TYPES))}"
            )
            continue

        enum_values = item.get("enum")
        if enum_values is not None:
            if not isinstance(enum_values, list):
                errors.append(f"{prefix}.enum must be an array when provided")
            else:
                for k, enum_value in enumerate(enum_values):
                    if not _is_typed_value(enum_value, value_type):
                        errors.append(
                            f"{prefix}.enum[{k}] must match value_type '{value_type}'"
                        )

        defs_by_id[attr_id] = item

    return defs_by_id


ECONOMIC_EXPOSURE_SUM_MIN = 99.5
ECONOMIC_EXPOSURE_SUM_MAX = 100.5


def _validate_economic_exposure(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object when provided")
        return
    breakdown = value.get("breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        errors.append(f"{path}.breakdown must be a non-empty array")
        return
    total = 0.0
    for idx, line in enumerate(breakdown):
        if not isinstance(line, dict):
            errors.append(f"{path}.breakdown[{idx}] must be an object")
            continue
        weight = line.get("weight_pct")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            errors.append(f"{path}.breakdown[{idx}].weight_pct must be numeric")
            continue
        if weight < 0 or weight > 100:
            errors.append(
                f"{path}.breakdown[{idx}].weight_pct ({weight}) must be between 0 and 100"
            )
            continue
        total += float(weight)
    if not (ECONOMIC_EXPOSURE_SUM_MIN <= total <= ECONOMIC_EXPOSURE_SUM_MAX):
        errors.append(
            f"{path}.breakdown weight_pct must sum to ~100 "
            f"(got {total}, tolerance {ECONOMIC_EXPOSURE_SUM_MIN}..{ECONOMIC_EXPOSURE_SUM_MAX})"
        )


def _validate_money(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object {{amount, currency}}")
        return
    amount = value.get("amount")
    currency = value.get("currency")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        errors.append(f"{path}.amount must be numeric")
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or currency != currency.upper()
    ):
        errors.append(f"{path}.currency must be ISO-4217 (3 uppercase letters)")
    if "fx_ref" in value:
        _validate_fx_ref(value.get("fx_ref"), currency, f"{path}.fx_ref", errors)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_fx_ref(
    value: Any, enclosing_currency: Any, path: str, errors: list[str]
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object when present")
        return
    as_of_date = value.get("as_of_date")
    base_currency = value.get("base_currency")
    quote_currency = value.get("quote_currency")
    rate_to_base = value.get("rate_to_base")
    if not isinstance(as_of_date, str) or not _DATE_RE.match(as_of_date):
        errors.append(f"{path}.as_of_date must be YYYY-MM-DD")
    else:
        try:
            datetime.strptime(as_of_date, "%Y-%m-%d")
        except ValueError:
            errors.append(f"{path}.as_of_date '{as_of_date}' is not a valid date")
    if (
        not isinstance(base_currency, str)
        or len(base_currency) != 3
        or base_currency != base_currency.upper()
    ):
        errors.append(f"{path}.base_currency must be ISO-4217 (3 uppercase letters)")
    if (
        not isinstance(quote_currency, str)
        or len(quote_currency) != 3
        or quote_currency != quote_currency.upper()
    ):
        errors.append(f"{path}.quote_currency must be ISO-4217 (3 uppercase letters)")
    elif (
        isinstance(enclosing_currency, str)
        and len(enclosing_currency) == 3
        and quote_currency != enclosing_currency.upper()
    ):
        errors.append(
            f"{path}.quote_currency '{quote_currency}' must equal the enclosing "
            f"Money.currency '{enclosing_currency}'"
        )
    if (
        not isinstance(rate_to_base, (int, float))
        or isinstance(rate_to_base, bool)
        or float(rate_to_base) <= 0
    ):
        errors.append(f"{path}.rate_to_base must be a positive number")


def _fx_ref_is_usable(fx_ref: Any, enclosing_currency: Any) -> bool:
    """Mirror ``_validate_fx_ref`` checks without recording errors.

    Returns ``True`` only when ``fx_ref`` has every field the structural
    validator would accept; provenance reporting treats any other shape
    as 'no usable audit trail' and falls through to the missing-fx_ref
    warning.
    """
    if not isinstance(fx_ref, dict) or not fx_ref:
        return False
    as_of_date = fx_ref.get("as_of_date")
    if not isinstance(as_of_date, str) or not _DATE_RE.match(as_of_date):
        return False
    try:
        datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        return False
    base_currency = fx_ref.get("base_currency")
    if (
        not isinstance(base_currency, str)
        or len(base_currency) != 3
        or base_currency != base_currency.upper()
    ):
        return False
    quote_currency = fx_ref.get("quote_currency")
    if (
        not isinstance(quote_currency, str)
        or len(quote_currency) != 3
        or quote_currency != quote_currency.upper()
    ):
        return False
    if (
        isinstance(enclosing_currency, str)
        and len(enclosing_currency) == 3
        and quote_currency != enclosing_currency.upper()
    ):
        return False
    rate_to_base = fx_ref.get("rate_to_base")
    if (
        not isinstance(rate_to_base, (int, float))
        or isinstance(rate_to_base, bool)
        or float(rate_to_base) <= 0
    ):
        return False
    return True


def _validate_account_id(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _ACCOUNT_ID_RE.match(value):
        errors.append(f"{path} must match pattern '^[a-z0-9_\\-]+$'")


def _validate_liabilities(
    liabilities: Any,
    holding_ids: set[str],
    errors: list[str],
) -> None:
    if liabilities is None:
        return
    if not isinstance(liabilities, list):
        errors.append("'liabilities' must be an array when provided")
        return
    seen: set[str] = set()
    for i, liability in enumerate(liabilities):
        prefix = f"liabilities[{i}]"
        if not isinstance(liability, dict):
            errors.append(f"{prefix} must be an object")
            continue
        lid = str(liability.get("id", "")).strip()
        if not lid:
            errors.append(f"{prefix}.id is required")
        elif lid in seen:
            errors.append(f"Duplicate liability id '{lid}'")
        else:
            seen.add(lid)

        kind = liability.get("kind")
        if kind is None:
            errors.append(f"{prefix}.kind is required")
        elif kind not in LIABILITY_KINDS:
            errors.append(
                f"{prefix}.kind '{kind}' must be one of: {', '.join(sorted(LIABILITY_KINDS))}"
            )

        if "balance" not in liability:
            errors.append(f"{prefix}.balance is required")
        else:
            _validate_money(liability.get("balance"), f"{prefix}.balance", errors)

        if "principal_original" in liability:
            _validate_money(
                liability.get("principal_original"),
                f"{prefix}.principal_original",
                errors,
            )

        if "account_id" in liability:
            _validate_account_id(
                liability.get("account_id"), f"{prefix}.account_id", errors
            )

        secured_by = liability.get("secured_by_holding_id")
        if (
            isinstance(secured_by, str)
            and secured_by
            and holding_ids
            and secured_by not in holding_ids
        ):
            errors.append(
                f"{prefix}.secured_by_holding_id '{secured_by}' not in holdings"
            )


def _validate_tax_lots(
    tax_lots: Any,
    holding_ids: set[str],
    errors: list[str],
) -> None:
    if tax_lots is None:
        return
    if not isinstance(tax_lots, list):
        errors.append("'tax_lots' must be an array when provided")
        return
    seen: set[str] = set()
    for i, lot in enumerate(tax_lots):
        prefix = f"tax_lots[{i}]"
        if not isinstance(lot, dict):
            errors.append(f"{prefix} must be an object")
            continue

        lot_id = str(lot.get("id", "")).strip()
        if not lot_id:
            errors.append(f"{prefix}.id is required")
        elif lot_id in seen:
            errors.append(f"Duplicate tax_lot id '{lot_id}'")
        else:
            seen.add(lot_id)

        holding_id = str(lot.get("holding_id", "")).strip()
        if not holding_id:
            errors.append(f"{prefix}.holding_id is required")
        elif holding_ids and holding_id not in holding_ids:
            errors.append(f"{prefix}.holding_id '{holding_id}' not in holdings")

        _validate_iso_datetime_field(
            lot.get("acquired_at"), f"{prefix}.acquired_at", errors, required=True
        )

        quantity = lot.get("quantity")
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
            errors.append(f"{prefix}.quantity is required and must be numeric")

        if "cost_basis" not in lot:
            errors.append(f"{prefix}.cost_basis is required")
        else:
            _validate_money(lot.get("cost_basis"), f"{prefix}.cost_basis", errors)

        if "unit_cost" in lot:
            _validate_money(lot.get("unit_cost"), f"{prefix}.unit_cost", errors)

        kind = lot.get("acquisition_kind")
        if kind is not None and kind not in TAX_LOT_ACQUISITION_KINDS:
            errors.append(
                f"{prefix}.acquisition_kind '{kind}' must be one of: "
                f"{', '.join(sorted(TAX_LOT_ACQUISITION_KINDS))}"
            )

        if "account_id" in lot:
            _validate_account_id(lot.get("account_id"), f"{prefix}.account_id", errors)

        # disposal consistency
        disposed_at = lot.get("disposed_at")
        _validate_iso_datetime_field(disposed_at, f"{prefix}.disposed_at", errors)
        disposal_activity_id = lot.get("disposal_activity_id")
        if disposal_activity_id and not disposed_at:
            errors.append(f"{prefix}.disposal_activity_id set without disposed_at")


def _validate_date_range(
    value: dict[str, Any], path: str, errors: list[str], *, required: bool = False
) -> None:
    valid = {}
    for key in ("from", "through"):
        if key not in value and not required:
            continue
        raw = value.get(key)
        try:
            if not isinstance(raw, str) or not _DATE_RE.fullmatch(raw):
                raise ValueError
            valid[key] = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            errors.append(f"{path}.{key} must be a valid YYYY-MM-DD date")
    if len(valid) == 2 and valid["from"] > valid["through"]:
        errors.append(f"{path}.from must not be after through")


def _validate_instrument_history(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    if value.get("status") not in ("complete", "partial", "unknown"):
        errors.append(f"{path}.status must be complete, partial or unknown")
    _validate_date_range(
        value, path, errors, required=value.get("status") == "complete"
    )
    if "notes" in value and (
        not isinstance(value["notes"], list)
        or any(not isinstance(note, str) for note in value["notes"])
    ):
        errors.append(f"{path}.notes must be an array of strings")
    periods = value.get("missing_periods", [])
    if not isinstance(periods, list):
        errors.append(f"{path}.missing_periods must be an array")
        return
    for i, period in enumerate(periods):
        prefix = f"{path}.missing_periods[{i}]"
        if not isinstance(period, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _validate_date_range(period, prefix, errors, required=True)
        if period.get("kind") not in (
            "transactions",
            "distributions",
            "corporate_actions",
            "all",
        ):
            errors.append(f"{prefix}.kind is invalid")


def _validate_corporate_action(
    value: Any,
    path: str,
    holding_ids: set[str],
    tax_lot_ids: set[str],
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    if value.get("kind") not in (
        "split",
        "reverse_split",
        "ticker_change",
        "merger",
        "subscription_conversion",
        "rights_issue",
    ):
        errors.append(f"{path}.kind is invalid")
    ratio = value.get("exchange_ratio")
    if "exchange_ratio" in value and (
        not _is_typed_value(ratio, "number") or ratio <= 0
    ):
        errors.append(f"{path}.exchange_ratio must be a positive number")
    legs = value.get("legs")
    if not isinstance(legs, list) or not legs:
        errors.append(f"{path}.legs must be a non-empty array")
        return
    for i, leg in enumerate(legs):
        prefix = f"{path}.legs[{i}]"
        if not isinstance(leg, dict):
            errors.append(f"{prefix} must be an object")
            continue
        hid = leg.get("holding_id")
        if not isinstance(hid, str) or not hid or hid not in holding_ids:
            errors.append(f"{prefix}.holding_id '{hid}' not in holdings")
        if not _is_typed_value(leg.get("quantity_delta"), "number"):
            errors.append(f"{prefix}.quantity_delta must be numeric")
        if "cost_basis_delta" in leg:
            _validate_money(
                leg["cost_basis_delta"], f"{prefix}.cost_basis_delta", errors
            )
        refs = leg.get("tax_lot_ids", [])
        if not isinstance(refs, list):
            errors.append(f"{prefix}.tax_lot_ids must be an array")
        else:
            for j, ref in enumerate(refs):
                if not isinstance(ref, str) or not ref or ref not in tax_lot_ids:
                    errors.append(
                        f"{prefix}.tax_lot_ids[{j}] '{ref}' not in tax_lots[].id"
                    )


def _validate_valuation(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    for field in ("unit_price", "net_value"):
        if field in value:
            _validate_money(value[field], f"{path}.{field}", errors)
    if "price_as_of" in value:
        _validate_iso_datetime_field(
            value["price_as_of"], f"{path}.price_as_of", errors, required=True
        )
    if "tax_provisions" in value:
        provisions = value["tax_provisions"]
        if not isinstance(provisions, list):
            errors.append(f"{path}.tax_provisions must be an array")
        else:
            for i, provision in enumerate(provisions):
                prefix = f"{path}.tax_provisions[{i}]"
                if not isinstance(provision, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                if (
                    not isinstance(provision.get("tax_type"), str)
                    or not provision["tax_type"]
                ):
                    errors.append(f"{prefix}.tax_type must be a nonempty string")
                _validate_money(provision.get("money"), f"{prefix}.money", errors)


def _validate_holding_observations(
    holding: dict[str, Any], path: str, errors: list[str]
) -> None:
    profile = holding.get("fixed_income_profile")
    coupon = profile.get("coupon") if isinstance(profile, dict) else None
    if isinstance(coupon, dict):
        coupon_path = f"{path}.fixed_income_profile.coupon"
        if "indexer_multiplier_pct" in coupon:
            multiplier = coupon["indexer_multiplier_pct"]
            if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
                errors.append(f"{coupon_path}.indexer_multiplier_pct must be numeric")
        if "reported_rate" in coupon and not isinstance(coupon["reported_rate"], str):
            errors.append(f"{coupon_path}.reported_rate must be a string")
        if "rate_scope" in coupon and coupon["rate_scope"] not in {
            "purchase",
            "weighted_average",
        }:
            errors.append(f"{coupon_path}.rate_scope is invalid")
    if "valuation" in holding:
        _validate_valuation(holding["valuation"], f"{path}.valuation", errors)
    if "acquisition_observations" not in holding:
        return
    observations = holding["acquisition_observations"]
    if not isinstance(observations, list):
        errors.append(f"{path}.acquisition_observations must be an array")
        return
    for i, observation in enumerate(observations):
        prefix = f"{path}.acquisition_observations[{i}]"
        if not isinstance(observation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("acquired_at", "observed_at"):
            _validate_iso_datetime_field(
                observation.get(field), f"{prefix}.{field}", errors, required=True
            )
        quantity = observation.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
            errors.append(f"{prefix}.quantity must be numeric")
        if observation.get("cost_basis_kind") not in {
            "reported_purchase_value",
            "broker_adjusted_purchase_value",
            "unknown",
        }:
            errors.append(f"{prefix}.cost_basis_kind is invalid")
        for field in ("unit_price", "reported_purchase_value", "market_value"):
            if field in observation:
                _validate_money(observation[field], f"{prefix}.{field}", errors)
        if "valuation" in observation:
            _validate_valuation(observation["valuation"], f"{prefix}.valuation", errors)
        for field in ("source_ref",):
            if field in observation and not isinstance(observation[field], str):
                errors.append(f"{prefix}.{field} must be a string")
        if "metadata" in observation and not isinstance(observation["metadata"], dict):
            errors.append(f"{prefix}.metadata must be an object")


def _validate_observation_date(value: Any, path: str, errors: list[str]) -> None:
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        errors.append(f"{path} must be a valid YYYY-MM-DD date")


def _validate_statement_observations(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("statement_observations must be an array")
        return
    ids: set[str] = set()
    for i, observation in enumerate(value):
        prefix = f"statement_observations[{i}]"
        if not isinstance(observation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("id", "provider"):
            if not isinstance(observation.get(field), str) or not observation[field]:
                errors.append(f"{prefix}.{field} must be a nonempty string")
        oid = observation.get("id")
        if isinstance(oid, str):
            if oid in ids:
                errors.append(f"{prefix}.id is duplicated")
            ids.add(oid)
        for field in ("period_start", "period_end"):
            _validate_observation_date(
                observation.get(field), f"{prefix}.{field}", errors
            )
        start, end = observation.get("period_start"), observation.get("period_end")
        if isinstance(start, str) and isinstance(end, str) and start > end:
            errors.append(f"{prefix}.period_end precedes period_start")
        if "issued_at" in observation:
            _validate_iso_datetime_field(
                observation["issued_at"], f"{prefix}.issued_at", errors, required=True
            )
        if "currency" in observation and (
            not isinstance(observation["currency"], str)
            or not re.fullmatch(r"[A-Z]{3}", observation["currency"])
        ):
            errors.append(f"{prefix}.currency must be ISO-4217")
        source = observation.get("source")
        if not isinstance(source, dict):
            errors.append(f"{prefix}.source must be an object")
        else:
            if not isinstance(source.get("path"), str) or not source["path"]:
                errors.append(f"{prefix}.source.path must be a nonempty string")
            digest = source.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(
                r"[a-fA-F0-9]{64}", digest
            ):
                errors.append(
                    f"{prefix}.source.sha256 must be 64 hexadecimal characters"
                )
            count = source.get("page_count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                errors.append(f"{prefix}.source.page_count must be a positive integer")
        for collection in ("balances", "sections"):
            if collection not in observation:
                continue
            rows = observation[collection]
            if not isinstance(rows, list):
                errors.append(f"{prefix}.{collection} must be an array")
                continue
            for j, row in enumerate(rows):
                row_path = f"{prefix}.{collection}[{j}]"
                if not isinstance(row, dict):
                    errors.append(f"{row_path} must be an object")
                    continue
                if collection == "balances":
                    if not isinstance(row.get("label"), str):
                        errors.append(f"{row_path}.label must be a string")
                    _validate_observation_date(
                        row.get("as_of"), f"{row_path}.as_of", errors
                    )
                    _validate_money(
                        row.get("gross_value"), f"{row_path}.gross_value", errors
                    )
                    if "net_value" in row:
                        _validate_money(
                            row["net_value"], f"{row_path}.net_value", errors
                        )
                else:
                    for field in ("name", "text"):
                        if not isinstance(row.get(field), str):
                            errors.append(f"{row_path}.{field} must be a string")
                    page = row.get("page")
                    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
                        errors.append(f"{row_path}.page must be a positive integer")
                    elif (
                        isinstance(source, dict)
                        and isinstance(source.get("page_count"), int)
                        and page > source["page_count"]
                    ):
                        errors.append(f"{row_path}.page exceeds source.page_count")
                    if "rows" in row and (
                        not isinstance(row["rows"], list)
                        or any(not isinstance(r, dict) for r in row["rows"])
                    ):
                        errors.append(f"{row_path}.rows must be an array of objects")
        for field in ("provider_account_id",):
            if field in observation and not isinstance(observation[field], str):
                errors.append(f"{prefix}.{field} must be a string")
        if "metadata" in observation and not isinstance(observation["metadata"], dict):
            errors.append(f"{prefix}.metadata must be an object")


def validate_portfolio(portfolio: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    missing = [k for k in CORE_TOP_LEVEL if k not in portfolio]
    if missing:
        errors.append(f"Missing top-level keys: {', '.join(sorted(missing))}")

    schema_uri = portfolio.get("schema_uri")
    if schema_uri is not None and not isinstance(schema_uri, str):
        errors.append("'schema_uri' must be a string")

    from .activities import check_financial_contract
    try:
        check_financial_contract(portfolio)
    except ValueError as exc:
        errors.append(str(exc))

    profile = portfolio.get("profile")
    if not isinstance(profile, dict):
        errors.append("'profile' must be an object")
    else:
        for k in ("portfolio_id", "owner_kind", "display_name"):
            if k not in profile:
                errors.append(f"'profile.{k}' is required")

    settings = portfolio.get("settings")
    if not isinstance(settings, dict):
        errors.append("'settings' must be an object")
    elif not settings.get("base_currency"):
        errors.append("'settings.base_currency' is required")

    catalog = portfolio.get("asset_type_catalog")
    if not isinstance(catalog, list):
        errors.append("'asset_type_catalog' must be an array")
        catalog_ids: set[str] = set()
        catalog_attr_defs: dict[str, dict[str, dict[str, Any]]] = {}
    else:
        catalog_ids = set()
        catalog_attr_defs = {}
        for i, asset_type in enumerate(catalog):
            if not isinstance(asset_type, dict):
                errors.append(f"asset_type_catalog[{i}] must be an object")
                continue
            if not asset_type.get("id"):
                errors.append(f"asset_type_catalog[{i}].id is required")
                continue
            type_id = str(asset_type["id"]).strip()
            catalog_ids.add(type_id)
            if not asset_type.get("asset_class"):
                errors.append(f"asset_type_catalog[{i}].asset_class is required")
            if type_id:
                catalog_attr_defs[type_id] = _collect_instrument_attribute_defs(
                    asset_type, i, errors
                )
            if "economic_exposure" in asset_type:
                _validate_economic_exposure(
                    asset_type.get("economic_exposure"),
                    f"asset_type_catalog[{i}].economic_exposure",
                    errors,
                )

    holdings = portfolio.get("holdings")
    holding_ids: set[str] = set()
    if not isinstance(holdings, list):
        errors.append("'holdings' must be an array")
    else:
        for i, holding in enumerate(holdings):
            if not isinstance(holding, dict):
                errors.append(f"holdings[{i}] must be an object")
                continue
            hid = str(holding.get("id", "")).strip()
            if not hid:
                errors.append(f"holdings[{i}].id is required")
            elif hid in holding_ids:
                errors.append(f"Duplicate holding id '{hid}'")
            else:
                holding_ids.add(hid)

            asset_type_id = str(holding.get("asset_type_id", "")).strip()
            if not asset_type_id:
                errors.append(f"holdings[{i}].asset_type_id is required")
            elif catalog_ids and asset_type_id not in catalog_ids:
                errors.append(
                    f"holdings[{i}].asset_type_id '{asset_type_id}' not in asset_type_catalog"
                )

            if "account_id" in holding:
                _validate_account_id(
                    holding.get("account_id"), f"holdings[{i}].account_id", errors
                )

            instrument_attrs = holding.get("instrument_attributes")
            if instrument_attrs is not None and not isinstance(instrument_attrs, dict):
                errors.append(
                    f"holdings[{i}].instrument_attributes must be an object when provided"
                )
            attrs_obj = instrument_attrs if isinstance(instrument_attrs, dict) else {}
            declared_attrs = catalog_attr_defs.get(asset_type_id, {})
            for attr_id, attr_def in declared_attrs.items():
                if attr_def.get("required") and attr_id not in attrs_obj:
                    errors.append(
                        f"holdings[{i}].instrument_attributes missing required key '{attr_id}' for asset_type_id '{asset_type_id}'"
                    )

            for attr_key, attr_value in attrs_obj.items():
                attr_def = declared_attrs.get(attr_key)
                if attr_def is None:
                    errors.append(
                        f"holdings[{i}].instrument_attributes.{attr_key} not declared for asset_type_id '{asset_type_id}'"
                    )
                    continue

                expected_type = str(attr_def.get("value_type", "")).strip()
                if not _is_typed_value(attr_value, expected_type):
                    errors.append(
                        f"holdings[{i}].instrument_attributes.{attr_key} must be {expected_type}"
                    )
                    continue

                enum_values = attr_def.get("enum")
                if (
                    isinstance(enum_values, list)
                    and enum_values
                    and attr_value not in enum_values
                ):
                    errors.append(
                        f"holdings[{i}].instrument_attributes.{attr_key} must be one of {enum_values}"
                    )

            if "economic_exposure" in holding:
                _validate_economic_exposure(
                    holding.get("economic_exposure"),
                    f"holdings[{i}].economic_exposure",
                    errors,
                )

            extensions = holding.get("extensions")
            if (
                isinstance(extensions, dict)
                and "rikdom_instrument_history" in extensions
            ):
                _validate_instrument_history(
                    extensions["rikdom_instrument_history"],
                    f"holdings[{i}].extensions.rikdom_instrument_history",
                    errors,
                )

            _validate_holding_observations(holding, f"holdings[{i}]", errors)

            market_value = holding.get("market_value")
            if not isinstance(market_value, dict):
                errors.append(
                    f"holdings[{i}].market_value is required and must be an object"
                )
            else:
                if not isinstance(market_value.get("amount"), (int, float)):
                    errors.append(f"holdings[{i}].market_value.amount must be numeric")
                currency = market_value.get("currency")
                if not isinstance(currency, str) or len(currency) != 3:
                    errors.append(
                        f"holdings[{i}].market_value.currency must be ISO-4217"
                    )
                if "fx_ref" in market_value:
                    _validate_fx_ref(
                        market_value.get("fx_ref"),
                        currency,
                        f"holdings[{i}].market_value.fx_ref",
                        errors,
                    )

    if "statement_observations" in portfolio:
        _validate_statement_observations(portfolio["statement_observations"], errors)

    activities = portfolio.get("activities", [])
    tax_lot_ids: set[str] = set()
    raw_tax_lots = portfolio.get("tax_lots")
    if isinstance(raw_tax_lots, list):
        for lot in raw_tax_lots:
            if isinstance(lot, dict):
                lid = lot.get("id")
                if isinstance(lid, str) and lid:
                    tax_lot_ids.add(lid)
    if activities is not None:
        if not isinstance(activities, list):
            errors.append("'activities' must be an array when provided")
        else:
            for i, activity in enumerate(activities):
                if not isinstance(activity, dict):
                    errors.append(f"activities[{i}] must be an object")
                    continue
                for k in ("id", "event_type", "status", "effective_at"):
                    if not activity.get(k):
                        errors.append(f"activities[{i}].{k} is required")

                for field in ("trade_at", "settled_at"):
                    if field in activity:
                        _validate_iso_datetime_field(
                            activity[field],
                            f"activities[{i}].{field}",
                            errors,
                            required=True,
                        )
                if "cost_basis_adjustment" in activity:
                    _validate_money(
                        activity["cost_basis_adjustment"],
                        f"activities[{i}].cost_basis_adjustment",
                        errors,
                    )
                if "corporate_action" in activity:
                    _validate_corporate_action(
                        activity["corporate_action"],
                        f"activities[{i}].corporate_action",
                        holding_ids,
                        tax_lot_ids,
                        errors,
                    )

                event_type = activity.get("event_type")
                if (
                    isinstance(event_type, str)
                    and event_type
                    and event_type not in ACTIVITY_EVENT_TYPES
                ):
                    errors.append(
                        f"activities[{i}].event_type '{event_type}' must be one of: "
                        f"{', '.join(sorted(ACTIVITY_EVENT_TYPES))}"
                    )

                if "account_id" in activity:
                    _validate_account_id(
                        activity.get("account_id"),
                        f"activities[{i}].account_id",
                        errors,
                    )

                if "holding_id" in activity:
                    h_ref = activity.get("holding_id")
                    if not isinstance(h_ref, str) or not h_ref:
                        errors.append(
                            f"activities[{i}].holding_id must be a non-empty string"
                        )
                    elif holding_ids and h_ref not in holding_ids:
                        errors.append(
                            f"activities[{i}].holding_id '{h_ref}' not in holdings"
                        )

                if "tax_lot_ids" in activity:
                    refs = activity.get("tax_lot_ids")
                    if not isinstance(refs, list):
                        errors.append(
                            f"activities[{i}].tax_lot_ids must be an array when provided"
                        )
                    else:
                        for j, ref in enumerate(refs):
                            if not isinstance(ref, str) or not ref:
                                errors.append(
                                    f"activities[{i}].tax_lot_ids[{j}] must be a non-empty string"
                                )
                                continue
                            if tax_lot_ids and ref not in tax_lot_ids:
                                errors.append(
                                    f"activities[{i}].tax_lot_ids[{j}] '{ref}' not in tax_lots[].id"
                                )

                if "money" in activity:
                    _validate_money(
                        activity.get("money"),
                        f"activities[{i}].money",
                        errors,
                    )
                if "fees" in activity:
                    _validate_money(
                        activity.get("fees"),
                        f"activities[{i}].fees",
                        errors,
                    )
                if "withholding_tax" in activity:
                    _validate_money(
                        activity.get("withholding_tax"),
                        f"activities[{i}].withholding_tax",
                        errors,
                    )
                if "realized_gain" in activity:
                    _validate_money(
                        activity.get("realized_gain"),
                        f"activities[{i}].realized_gain",
                        errors,
                    )
                if "counter_money" in activity:
                    _validate_money(
                        activity.get("counter_money"),
                        f"activities[{i}].counter_money",
                        errors,
                    )

                if event_type == "fx_conversion":
                    if "counter_money" not in activity:
                        errors.append(
                            f"activities[{i}].counter_money is required for fx_conversion events"
                        )
                    fx_rate = activity.get("fx_rate")
                    if fx_rate is not None and (
                        not isinstance(fx_rate, (int, float))
                        or isinstance(fx_rate, bool)
                        or fx_rate <= 0
                    ):
                        errors.append(
                            f"activities[{i}].fx_rate must be a positive number"
                        )

    operations = portfolio.get("operations")
    if operations is not None:
        if not isinstance(operations, dict):
            errors.append("'operations' must be an object when provided")
        else:
            tasks = operations.get("task_catalog", [])
            events = operations.get("task_events", [])

            task_ids: set[str] = set()
            if not isinstance(tasks, list):
                errors.append(
                    "'operations.task_catalog' must be an array when provided"
                )
            else:
                for i, task in enumerate(tasks):
                    if not isinstance(task, dict):
                        errors.append(f"operations.task_catalog[{i}] must be an object")
                        continue
                    for k in ("id", "label", "category", "status", "cadence"):
                        if not task.get(k):
                            errors.append(
                                f"operations.task_catalog[{i}].{k} is required"
                            )

                    tid = str(task.get("id", "")).strip()
                    if tid:
                        if tid in task_ids:
                            errors.append(f"Duplicate operations task id '{tid}'")
                        task_ids.add(tid)

                    cadence = task.get("cadence")
                    if cadence is not None:
                        if not isinstance(cadence, dict):
                            errors.append(
                                f"operations.task_catalog[{i}].cadence must be an object"
                            )
                        elif not cadence.get("frequency"):
                            errors.append(
                                f"operations.task_catalog[{i}].cadence.frequency is required"
                            )

            event_ids: set[str] = set()
            if not isinstance(events, list):
                errors.append("'operations.task_events' must be an array when provided")
            else:
                for i, event in enumerate(events):
                    if not isinstance(event, dict):
                        errors.append(f"operations.task_events[{i}] must be an object")
                        continue
                    for k in ("id", "task_id", "event_type", "occurred_at"):
                        if not event.get(k):
                            errors.append(
                                f"operations.task_events[{i}].{k} is required"
                            )

                    eid = str(event.get("id", "")).strip()
                    if eid:
                        if eid in event_ids:
                            errors.append(f"Duplicate operations task event id '{eid}'")
                        event_ids.add(eid)

                    task_id = str(event.get("task_id", "")).strip()
                    if task_id and task_id not in task_ids:
                        errors.append(
                            f"operations.task_events[{i}].task_id '{task_id}' not in operations.task_catalog"
                        )

            if isinstance(tasks, list):
                for i, task in enumerate(tasks):
                    if not isinstance(task, dict):
                        continue
                    last_event_id = str(task.get("last_event_id", "")).strip()
                    if last_event_id and last_event_id not in event_ids:
                        errors.append(
                            f"operations.task_catalog[{i}].last_event_id '{last_event_id}' not in operations.task_events"
                        )

    _validate_liabilities(portfolio.get("liabilities"), holding_ids, errors)
    _validate_tax_lots(portfolio.get("tax_lots"), holding_ids, errors)

    return errors


def validate_fx_provenance(portfolio: dict[str, Any]) -> list[str]:
    """Soft warnings when foreign-currency Money values lack fx_ref provenance.

    Returns one warning per holdings[].market_value (and activities[].money) whose
    currency differs from settings.base_currency and where no fx_ref is stamped.
    Such values rely on aggregate-time FX lookup, which works but loses the
    line-item audit trail (which fx_rates.jsonl row was used).
    """
    warnings: list[str] = []
    if not isinstance(portfolio, dict):
        return warnings
    settings = portfolio.get("settings")
    base = (
        settings.get("base_currency")
        if isinstance(settings, dict) and isinstance(settings.get("base_currency"), str)
        else None
    )
    if not base:
        return warnings
    base = base.strip().upper()

    def _check(money: Any, path: str) -> None:
        if not isinstance(money, dict):
            return
        currency = money.get("currency")
        if not isinstance(currency, str):
            return
        if currency.strip().upper() == base:
            return
        if "fx_ref" in money and _fx_ref_is_usable(money.get("fx_ref"), currency):
            fx_ref = money.get("fx_ref")
            ref_base = fx_ref.get("base_currency") if isinstance(fx_ref, dict) else None
            if isinstance(ref_base, str) and ref_base.strip().upper() != base:
                warnings.append(
                    f"{path}.fx_ref.base_currency '{ref_base}' does not match "
                    f"settings.base_currency '{base}'"
                )
            return
        # Missing or malformed fx_ref both leave the audit trail absent.
        warnings.append(
            f"{path} is in {currency} but has no fx_ref; base-currency conversion "
            f"to {base} cannot be sourced to a specific fx_rates.jsonl row"
        )

    holdings = portfolio.get("holdings")
    if isinstance(holdings, list):
        for i, holding in enumerate(holdings):
            if isinstance(holding, dict):
                _check(holding.get("market_value"), f"holdings[{i}].market_value")

    activities = portfolio.get("activities")
    if isinstance(activities, list):
        for i, activity in enumerate(activities):
            if isinstance(activity, dict):
                _check(activity.get("money"), f"activities[{i}].money")

    return warnings


def collect_policy_account_ids(policy: Any) -> set[str]:
    """Return the set of account_id strings declared in a policy document.

    A missing/invalid policy yields an empty set; callers should treat that
    as 'no cross-file check possible' rather than as a failure.
    """
    if not isinstance(policy, dict):
        return set()
    accounts = policy.get("accounts")
    if not isinstance(accounts, list):
        return set()
    out: set[str] = set()
    for account in accounts:
        if not isinstance(account, dict):
            continue
        aid = account.get("account_id")
        if isinstance(aid, str) and aid:
            out.add(aid)
    return out


def _collect_holding_account_ids(holdings: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(holdings, list):
        return out
    for i, holding in enumerate(holdings):
        if not isinstance(holding, dict):
            continue
        aid = holding.get("account_id")
        if isinstance(aid, str) and aid:
            out.append((f"holdings[{i}].account_id", aid))
    return out


def _collect_attr_account_ids(items: Any, parent: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(items, list):
        return out
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        aid = item.get("account_id")
        if isinstance(aid, str) and aid:
            out.append((f"{parent}[{i}].account_id", aid))
    return out


def cross_validate_account_ids(
    portfolio: dict[str, Any], policy: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Cross-file referential integrity for account_id soft references.

    Returns (errors, warnings):
    - errors: account_id values that don't resolve in policy.accounts.
    - warnings: holdings without an account_id when a policy is present
      (so agents see what's unassigned without blocking validation).
    """
    errors: list[str] = []
    warnings: list[str] = []
    declared = collect_policy_account_ids(policy)
    if not declared:
        return errors, warnings

    refs: list[tuple[str, str]] = []
    refs.extend(_collect_holding_account_ids(portfolio.get("holdings")))
    refs.extend(_collect_attr_account_ids(portfolio.get("liabilities"), "liabilities"))
    refs.extend(_collect_attr_account_ids(portfolio.get("tax_lots"), "tax_lots"))
    refs.extend(_collect_attr_account_ids(portfolio.get("activities"), "activities"))

    for path, aid in refs:
        if aid not in declared:
            errors.append(
                f"{path} '{aid}' not declared in policy.accounts[].account_id"
            )

    holdings = portfolio.get("holdings")
    if isinstance(holdings, list):
        for i, holding in enumerate(holdings):
            if not isinstance(holding, dict):
                continue
            if "account_id" not in holding:
                warnings.append(
                    f"holdings[{i}] has no account_id; placement-aware analysis "
                    "(tax-location, per-account drift) will treat it as unassigned"
                )
    return errors, warnings
