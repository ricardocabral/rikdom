"""Read explicit, opaque identity keys supplied by trusted source plugins.

Core never constructs identity from geography, taxonomy, or identifiers.
"""
from __future__ import annotations

from typing import Any


def holding_canonical_key(holding: dict[str, Any]) -> str | None:
    """Read a stored canonical key, preferring the explicit metadata field."""
    if not isinstance(holding, dict):
        return None
    meta = holding.get("metadata")
    if isinstance(meta, dict):
        key = meta.get("canonical_key")
        if isinstance(key, str) and key.strip():
            return key
    return None
