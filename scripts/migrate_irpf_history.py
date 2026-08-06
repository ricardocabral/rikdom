#!/usr/bin/env python3
"""Archive an IRPF declaration without replacing current portfolio positions."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from rikdom.storage import save_json


def _is_zero_value_irpf_holding(holding: dict[str, Any]) -> bool:
    value = holding.get("market_value")
    return (
        isinstance(holding.get("id"), str)
        and holding["id"].startswith("irpf-")
        and isinstance(value, dict)
        and value.get("currency") == "BRL"
        and isinstance(value.get("amount"), (int, float))
        and not isinstance(value["amount"], bool)
        and value["amount"] == 0
    )


def split_active_holdings(portfolio: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a copied active portfolio and its zero-value IRPF legacy rows."""
    active = copy.deepcopy(portfolio)
    holdings = active.get("holdings", [])
    archived = [copy.deepcopy(item) for item in holdings if _is_zero_value_irpf_holding(item)]
    active["holdings"] = [item for item in holdings if not _is_zero_value_irpf_holding(item)]
    return active, archived


def enrich_active_legacy_holdings(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Add only schema-required, explicitly conservative data to live IRPF rows."""
    enriched = copy.deepcopy(portfolio)
    categories = {
        "37368116000198": "RENDA_FIXA",
        "34096235000140": "RENDA_FIXA",
        "30934757000113": "RENDA_FIXA",
        "11182072000113": "MULTIMERCADO",
        "35002927000145": "MULTIMERCADO",
        "17400251000166": "ACOES",
    }
    for holding in enriched.get("holdings", []):
        cnpj = "".join(filter(str.isdigit, str(holding.get("identifiers", {}).get("cnpj", ""))))
        if holding.get("asset_type_id") == "fundo_investimento" and cnpj in categories:
            attrs = holding.setdefault("instrument_attributes", {})
            attrs.setdefault("category", categories[cnpj])
            attrs.setdefault("tax_profile.ir_pf_treatment", "OUTRO")
    catalog = enriched.setdefault("asset_type_catalog", [])
    if not any(item.get("id") == "vehicle" for item in catalog):
        catalog.append({"id": "vehicle", "label": "Vehicle", "asset_class": "other"})
    return enriched


def _load_irpf_importer():
    path = Path(__file__).resolve().parents[1] / "plugins" / "irpf-xml" / "importer.py"
    spec = importlib.util.spec_from_file_location("rikdom_irpf_history_importer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load IRPF importer at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_history_document(xml_path: Path) -> dict[str, Any]:
    payload = _load_irpf_importer().parse_statement(xml_path)
    return {
        "schema_version": "1.0",
        "kind": "irpf_declaration_history",
        "source": {
            "file_name": xml_path.name,
            "sha256": hashlib.sha256(xml_path.read_bytes()).hexdigest(),
            "provider": payload["provider"],
        },
        "reference_date": payload["metadata"]["current_year_end"],
        "declaration": payload,
    }


def run_migration(portfolio_path: Path, xml_path: Path, archive_path: Path, *, write: bool) -> dict[str, Any]:
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    active, archived = split_active_holdings(portfolio)
    active = enrich_active_legacy_holdings(active)
    history = build_history_document(xml_path)
    result = {
        "dry_run": not write,
        "archived_count": len(archived),
        "active_holdings_count": len(active.get("holdings", [])),
        "xml_holdings_count": len(history["declaration"]["holdings"]),
        "archive_path": str(archive_path),
        "removed_ids": [item["id"] for item in archived],
    }
    if not write:
        return result
    backup_path = portfolio_path.with_name(f"{portfolio_path.name}.bak-irpf-history")
    if not backup_path.exists():
        save_json(backup_path, portfolio)
    save_json(archive_path, history)
    save_json(portfolio_path, active)
    result["backup_path"] = str(backup_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True, dest="xml_path")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_migration(args.portfolio, args.xml_path, args.archive, write=args.write), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
