#!/usr/bin/env python3
"""Reapply FII tijolo/papel/hibrido classification to a portfolio file.

B3 re-imports replace holdings wholesale (see ``merge_holdings`` in
``src/rikdom/plugins.py``), wiping any locally curated
``instrument_attributes``. This script makes the classification reapplicable:
the mapping lives in a JSON file next to the portfolio (default
``data/fii_classification.json``) and can be applied after every import.

The mapping file maps B3 tickers to classification payloads:

    {
      "schema": "rikdom.fii_classification/1",
      "classifications": {
        "HGLG11": {"fii_type": "TIJOLO", "segment": "Logistica"},
        "KNCR11": {"fii_type": "PAPEL", "segment": "CRI CDI high grade"}
      }
    }

Behavior:
- Ensures the embedded ``asset_type_catalog`` entries for ``reit`` and
  ``fund`` declare optional ``fii_type``/``segment``/``b3_ticker`` attributes
  so validation accepts the holding-level values.
- Applies the mapping to holdings whose identifier ticker matches and whose
  ``asset_type_id`` is one of the live-position types (``reit``, ``fund``).
- Idempotent: re-running with the same inputs is a no-op.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FII_TYPE_ENUM = ["TIJOLO", "PAPEL", "HIBRIDO", "FOF", "DESENVOLVIMENTO"]
TARGET_ASSET_TYPE_IDS = ("reit", "fund")
CATALOG_TYPES_TO_EXTEND = ("reit", "fund")
MAPPING_SCHEMA = "rikdom.fii_classification/1"


def _optional_attr(attr_id: str, label: str, enum: list[str] | None = None) -> dict:
    attr: dict[str, Any] = {
        "id": attr_id,
        "label": label,
        "value_type": "string",
        "required": False,
    }
    if enum:
        attr["enum"] = enum
    return attr


def ensure_catalog_attributes(portfolio: dict[str, Any]) -> int:
    """Declare optional FII attributes on reit/fund catalog entries."""
    added = 0
    catalog = portfolio.get("asset_type_catalog")
    if not isinstance(catalog, list):
        return added
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") not in CATALOG_TYPES_TO_EXTEND:
            continue
        attrs = entry.setdefault("instrument_attributes", [])
        declared = {a.get("id") for a in attrs if isinstance(a, dict)}
        if "fii_type" not in declared:
            attrs.append(_optional_attr("fii_type", "FII Type", FII_TYPE_ENUM))
            added += 1
        if "segment" not in declared:
            attrs.append(_optional_attr("segment", "Segment"))
            added += 1
        if "b3_ticker" not in declared:
            attrs.append(_optional_attr("b3_ticker", "B3 Ticker"))
            added += 1
    return added


def load_mapping(path: Path) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != MAPPING_SCHEMA:
        raise ValueError(
            f"{path}: expected schema '{MAPPING_SCHEMA}', got {payload.get('schema')!r}"
        )
    classifications = payload.get("classifications")
    if not isinstance(classifications, dict):
        raise ValueError(f"{path}: 'classifications' must be an object")
    out: dict[str, dict[str, str]] = {}
    for ticker, entry in classifications.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: classification for {ticker} must be an object")
        fii_type = entry.get("fii_type")
        if fii_type not in FII_TYPE_ENUM:
            raise ValueError(
                f"{path}: {ticker}.fii_type must be one of {FII_TYPE_ENUM}, got {fii_type!r}"
            )
        out[ticker.strip().upper()] = entry
    return out


def apply_classification(
    portfolio: dict[str, Any], mapping: dict[str, dict[str, str]]
) -> dict[str, list[str]]:
    """Apply mapping to live holdings; returns applied/unchanged/unmatched tickers."""
    applied: list[str] = []
    unchanged: list[str] = []
    seen: set[str] = set()
    for holding in portfolio.get("holdings", []) or []:
        if not isinstance(holding, dict):
            continue
        if holding.get("asset_type_id") not in TARGET_ASSET_TYPE_IDS:
            continue
        ticker = str((holding.get("identifiers") or {}).get("ticker") or "").upper()
        entry = mapping.get(ticker)
        if not entry:
            continue
        seen.add(ticker)
        attrs = holding.setdefault("instrument_attributes", {})
        desired = {
            "fii_type": entry["fii_type"],
            "segment": entry.get("segment", ""),
            "b3_ticker": ticker,
        }
        desired = {k: v for k, v in desired.items() if v}
        if all(attrs.get(k) == v for k, v in desired.items()):
            unchanged.append(ticker)
            continue
        attrs.update(desired)
        applied.append(ticker)
    unmatched = sorted(set(mapping) - seen)
    return {"applied": applied, "unchanged": unchanged, "unmatched": unmatched}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--portfolio", default="data/portfolio.json")
    parser.add_argument("--mapping", default="data/fii_classification.json")
    parser.add_argument(
        "--dry-run", action="store_true", help="report changes without writing"
    )
    parser.add_argument(
        "--no-backup", action="store_true", help="skip portfolio backup before writing"
    )
    args = parser.parse_args(argv)

    portfolio_path = Path(args.portfolio)
    mapping_path = Path(args.mapping)
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    mapping = load_mapping(mapping_path)

    catalog_added = ensure_catalog_attributes(portfolio)
    result = apply_classification(portfolio, mapping)

    changed = bool(result["applied"]) or catalog_added > 0
    print(f"catalog attributes added: {catalog_added}")
    print(f"applied:   {len(result['applied'])} {' '.join(result['applied'])}")
    print(f"unchanged: {len(result['unchanged'])}")
    if result["unmatched"]:
        print(
            f"unmatched (no live holding): {' '.join(result['unmatched'])}",
            file=sys.stderr,
        )

    if not changed:
        print("nothing to do")
        return 0
    if args.dry_run:
        print("dry-run: portfolio not written")
        return 0

    if not args.no_backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = portfolio_path.with_name(f"{portfolio_path.name}.bak-{stamp}")
        shutil.copy2(portfolio_path, backup)
        print(f"backup: {backup}")

    portfolio_path.write_text(
        json.dumps(portfolio, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {portfolio_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
