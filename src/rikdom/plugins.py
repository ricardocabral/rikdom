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

    if not isinstance(payload, dict) or not isinstance(payload.get("holdings"), list):
        raise PluginError("Plugin output must be an object with 'holdings' array")

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
    for entry in imported.get("holdings", []):
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
