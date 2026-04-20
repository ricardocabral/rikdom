from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class PluginError(RuntimeError):
    pass



def _read_manifest(plugin_dir: Path) -> dict[str, Any]:
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        raise PluginError(f"Missing plugin manifest: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def run_import_plugin(
    plugin_name: str,
    input_path: str,
    plugins_root: str | Path,
) -> dict[str, Any]:
    input_path = str(Path(input_path).resolve())
    plugin_dir = Path(plugins_root) / plugin_name
    if not plugin_dir.exists():
        raise PluginError(f"Plugin '{plugin_name}' not found in {plugins_root}")

    manifest = _read_manifest(plugin_dir)
    command = manifest.get("command")
    if not isinstance(command, list) or not command:
        raise PluginError("plugin.json field 'command' must be a non-empty array")

    resolved_cmd = []
    for i, part in enumerate(command):
        segment = str(part)
        if i == 0 and not Path(segment).is_absolute() and "/" in segment:
            resolved_cmd.append(str((plugin_dir / segment).resolve()))
        else:
            resolved_cmd.append(segment)

    resolved_cmd.append(input_path)

    proc = subprocess.run(
        resolved_cmd,
        cwd=str(plugin_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise PluginError(
            f"Plugin '{plugin_name}' failed with code {proc.returncode}: {proc.stderr.strip()}"
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PluginError(f"Plugin '{plugin_name}' produced invalid JSON output") from exc

    if not isinstance(payload, dict):
        raise PluginError("Plugin output must be a JSON object")

    holdings = payload.get("holdings")
    activities = payload.get("activities")
    has_holdings = isinstance(holdings, list)
    has_activities = isinstance(activities, list)
    if not has_holdings and not has_activities:
        raise PluginError(
            "Plugin output must contain a 'holdings' array, an 'activities' array, or both"
        )
    if "holdings" in payload and not has_holdings:
        raise PluginError("Plugin output field 'holdings' must be an array when present")
    if "activities" in payload and not has_activities:
        raise PluginError("Plugin output field 'activities' must be an array when present")

    return payload


def merge_holdings(portfolio: dict[str, Any], imported: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    holdings = portfolio.get("holdings")
    if not isinstance(holdings, list):
        holdings = []
        portfolio["holdings"] = holdings

    current_index: dict[str, int] = {}
    for i, item in enumerate(holdings):
        if isinstance(item, dict) and item.get("id"):
            current_index[str(item["id"])] = i

    inserted = 0
    updated = 0
    for entry in imported.get("holdings", []) or []:
        if not isinstance(entry, dict):
            continue
        hid = str(entry.get("id", "")).strip()
        if not hid:
            continue

        if hid in current_index:
            holdings[current_index[hid]] = entry
            updated += 1
        else:
            holdings.append(entry)
            current_index[hid] = len(holdings) - 1
            inserted += 1

    return portfolio, inserted, updated


def _activity_key(entry: dict[str, Any]) -> str | None:
    idem = str(entry.get("idempotency_key", "")).strip()
    if idem:
        return f"idem::{idem}"
    aid = str(entry.get("id", "")).strip()
    if aid:
        return f"id::{aid}"
    return None


def merge_activities(
    portfolio: dict[str, Any], imported: dict[str, Any]
) -> tuple[dict[str, Any], int, int]:
    activities = portfolio.get("activities")
    if not isinstance(activities, list):
        activities = []
        portfolio["activities"] = activities

    current_index: dict[str, int] = {}
    for i, item in enumerate(activities):
        if not isinstance(item, dict):
            continue
        key = _activity_key(item)
        if key is not None:
            current_index[key] = i

    inserted = 0
    updated = 0
    for entry in imported.get("activities", []) or []:
        if not isinstance(entry, dict):
            continue
        key = _activity_key(entry)
        if key is None:
            continue

        normalized = dict(entry)
        normalized.setdefault("status", "posted")

        if key in current_index:
            activities[current_index[key]] = normalized
            updated += 1
        else:
            activities.append(normalized)
            current_index[key] = len(activities) - 1
            inserted += 1

    return portfolio, inserted, updated
