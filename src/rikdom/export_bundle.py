from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .policy import CANONICAL_POLICY_SCHEMA_URI
from .validate import CANONICAL_SCHEMA_URI

EXPORT_FORMAT = "rikdom-export"
EXPORT_VERSION = "1.0.0"
MANIFEST_PATH = "rikdom-export.json"
SNAPSHOT_SCHEMA_URI = "https://example.org/rikdom/schema/snapshot.schema.json"
FX_RATES_SCHEMA_URI = "https://example.org/rikdom/schema/fx-rates.jsonl"
SUPPORTED_KINDS = {"portfolio", "snapshots", "fx_history", "policy"}
REQUIRED_KINDS = {"portfolio"}


class ExportBundleError(ValueError):
    """Raised when an export bundle cannot be built or verified."""


@dataclass(frozen=True)
class BundleFile:
    kind: str
    path: str
    source: Path
    required: bool = False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_schema_ref(
    data: bytes, default_uri: str | None = None
) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return default_uri, None
    if not isinstance(payload, dict):
        return default_uri, None
    schema_uri = payload.get("schema_uri")
    schema_version = payload.get("schema_version")
    return (
        schema_uri if isinstance(schema_uri, str) else default_uri,
        schema_version if isinstance(schema_version, str) else None,
    )


def _jsonl_record_count(data: bytes) -> int:
    count = 0
    for raw_line in data.splitlines():
        if raw_line.strip():
            count += 1
    return count


def _entry_for(bundle_file: BundleFile, data: bytes) -> dict[str, Any]:
    schema_uri: str | None = None
    schema_version: str | None = None
    media_type = "application/octet-stream"
    record_count: int | None = None

    if bundle_file.path.endswith(".json"):
        media_type = "application/json"
        default_uri = {
            "portfolio": CANONICAL_SCHEMA_URI,
            "policy": CANONICAL_POLICY_SCHEMA_URI,
        }.get(bundle_file.kind)
        schema_uri, schema_version = _json_schema_ref(data, default_uri)
    elif bundle_file.path.endswith(".jsonl"):
        media_type = "application/x-jsonlines"
        record_count = _jsonl_record_count(data)
        if bundle_file.kind == "snapshots":
            schema_uri = SNAPSHOT_SCHEMA_URI
        elif bundle_file.kind == "fx_history":
            schema_uri = FX_RATES_SCHEMA_URI

    entry: dict[str, Any] = {
        "path": bundle_file.path,
        "kind": bundle_file.kind,
        "media_type": media_type,
        "bytes": len(data),
        "sha256": _sha256(data),
    }
    if schema_uri:
        entry["schema_uri"] = schema_uri
    if schema_version:
        entry["schema_version"] = schema_version
    if record_count is not None:
        entry["records"] = record_count
    return entry


def create_export_bundle(
    output: str | Path,
    *,
    created_at: str,
    portfolio: str | Path,
    snapshots: str | Path | None = None,
    fx_history: str | Path | None = None,
    policy: str | Path | None = None,
) -> dict[str, Any]:
    """Create a portable rikdom export zip and return its manifest."""
    files = [BundleFile("portfolio", "data/portfolio.json", Path(portfolio), True)]
    if snapshots is not None:
        files.append(BundleFile("snapshots", "data/snapshots.jsonl", Path(snapshots)))
    if fx_history is not None:
        files.append(BundleFile("fx_history", "data/fx_rates.jsonl", Path(fx_history)))
    if policy is not None:
        files.append(BundleFile("policy", "data/policy.json", Path(policy)))

    entries: list[dict[str, Any]] = []
    payloads: list[tuple[BundleFile, bytes]] = []
    for bundle_file in files:
        if not bundle_file.source.exists():
            if bundle_file.required:
                raise ExportBundleError(
                    f"Required export input not found: {bundle_file.source}"
                )
            continue
        if not bundle_file.source.is_file():
            raise ExportBundleError(f"Export input is not a file: {bundle_file.source}")
        data = bundle_file.source.read_bytes()
        entries.append(_entry_for(bundle_file, data))
        payloads.append((bundle_file, data))

    manifest: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_VERSION,
        "created_at": created_at,
        "entries": entries,
    }

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            MANIFEST_PATH, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )
        for bundle_file, data in payloads:
            zf.writestr(bundle_file.path, data)
    return manifest


def verify_export_bundle(bundle: str | Path) -> dict[str, Any]:
    """Verify all manifest checksums and return the parsed manifest."""
    with zipfile.ZipFile(bundle, "r") as zf:
        names = set(zf.namelist())
        if MANIFEST_PATH not in names:
            raise ExportBundleError(f"Bundle missing {MANIFEST_PATH}")
        try:
            manifest = json.loads(zf.read(MANIFEST_PATH).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExportBundleError(f"Invalid {MANIFEST_PATH}: {exc}") from exc

        if not isinstance(manifest, dict):
            raise ExportBundleError(f"Invalid {MANIFEST_PATH}: expected object")
        if manifest.get("format") != EXPORT_FORMAT:
            raise ExportBundleError("Not a rikdom-export bundle")
        if manifest.get("format_version") != EXPORT_VERSION:
            raise ExportBundleError(
                f"Unsupported rikdom-export version: {manifest.get('format_version')}"
            )
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise ExportBundleError("Bundle manifest missing entries list")

        seen: set[str] = set()
        seen_kinds: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ExportBundleError(f"Manifest entry {index} is not an object")
            path = entry.get("path")
            if (
                not isinstance(path, str)
                or path.startswith("/")
                or ".." in Path(path).parts
            ):
                raise ExportBundleError(f"Manifest entry {index} has unsafe path")
            kind = entry.get("kind")
            if not isinstance(kind, str) or kind not in SUPPORTED_KINDS:
                raise ExportBundleError(f"Unsupported manifest kind: {kind}")
            if kind in seen_kinds:
                raise ExportBundleError(f"Duplicate manifest kind: {kind}")
            seen_kinds.add(kind)
            if path in seen:
                raise ExportBundleError(f"Duplicate manifest path: {path}")
            seen.add(path)
            if path not in names:
                raise ExportBundleError(f"Bundle missing payload: {path}")
            data = zf.read(path)
            expected_size = entry.get("bytes")
            if not isinstance(expected_size, int) or expected_size != len(data):
                raise ExportBundleError(f"Size mismatch for {path}")
            expected_sha = entry.get("sha256")
            if not isinstance(expected_sha, str) or expected_sha != _sha256(data):
                raise ExportBundleError(f"Checksum mismatch for {path}")
        missing_required = REQUIRED_KINDS - seen_kinds
        if missing_required:
            missing = ", ".join(sorted(missing_required))
            raise ExportBundleError(
                f"Bundle missing required payload kind(s): {missing}"
            )
        return manifest


def read_verified_payloads(
    bundle: str | Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Verify a bundle, then return manifest plus payload bytes by kind."""
    manifest = verify_export_bundle(bundle)
    payloads: dict[str, bytes] = {}
    with zipfile.ZipFile(bundle, "r") as zf:
        for entry in manifest["entries"]:
            kind = entry.get("kind")
            path = entry.get("path")
            if isinstance(kind, str) and isinstance(path, str):
                payloads[kind] = zf.read(path)
    return manifest, payloads
