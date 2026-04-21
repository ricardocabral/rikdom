"""Journal verification, compaction, and rotation utilities.

Rikdom's append-only journals (e.g. ``data/snapshots.jsonl``,
``data/import-log.jsonl``) are written line-by-line via
:func:`rikdom.storage.append_jsonl`. This module handles two operations
that a plain append path cannot:

* **Compaction** — collapse a long snapshot history into a policy-driven
  retention window (daily 30d / weekly 1y / monthly older by default).
* **Rotation** — when a journal grows past a size threshold, move it aside
  to a dated sibling so new appends start with a fresh file.

Both operations write the replacement atomically (tempfile + ``os.replace``)
and leave a ``.bak`` sibling for one cycle so recovery is always possible.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .storage import fsync_dir, load_jsonl

logger = logging.getLogger(__name__)

DEFAULT_ROTATE_BYTES = 16 * 1024 * 1024  # 16 MiB


@dataclass(frozen=True)
class CompactionPolicy:
    """Retention buckets for snapshot compaction.

    The default mirrors the PRD guidance: keep every snapshot for the last
    ``daily_days`` days, then one per ISO week for ``weekly_days`` days,
    and one per calendar month beyond that.
    """

    daily_days: int = 30
    weekly_days: int = 365
    # Beyond weekly_days: one per calendar month. No hard cap.


DEFAULT_POLICY = CompactionPolicy()


@dataclass(frozen=True)
class VerifyResult:
    ok_rows: int
    torn_tail_bytes: int
    total_bytes: int


def verify_journal(path: str | Path) -> VerifyResult:
    """Report how many rows parse cleanly and how many bytes are a torn tail."""
    p = Path(path)
    if not p.exists():
        return VerifyResult(0, 0, 0)
    raw = p.read_bytes()
    total = len(raw)
    ok = 0
    offset = 0
    last_good_end = 0
    while offset < total:
        nl = raw.find(b"\n", offset)
        if nl == -1:
            break
        line = raw[offset:nl].decode("utf-8", errors="replace").strip()
        offset = nl + 1
        if not line:
            last_good_end = offset
            continue
        try:
            json.loads(line)
            ok += 1
            last_good_end = offset
        except json.JSONDecodeError:
            last_good_end = offset
    torn = total - last_good_end
    return VerifyResult(ok_rows=ok, torn_tail_bytes=torn, total_bytes=total)


def _parse_snapshot_ts(row: dict[str, Any]) -> datetime | None:
    raw = row.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket_key(ts: datetime, today: date, policy: CompactionPolicy) -> str:
    """Return an opaque bucket id. Snapshots sharing a bucket collapse to one.

    Recent rows get per-second buckets (i.e. never collapse); older rows
    collapse to week, then month.
    """
    age = (today - ts.date()).days
    if age < policy.daily_days:
        return f"s:{ts.isoformat()}"
    if age < policy.weekly_days:
        iso_year, iso_week, _ = ts.isocalendar()
        return f"w:{iso_year}-{iso_week:02d}"
    return f"m:{ts.year}-{ts.month:02d}"


def select_compacted(
    rows: Iterable[dict[str, Any]],
    *,
    policy: CompactionPolicy = DEFAULT_POLICY,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return the subset of rows kept under ``policy`` (pure, no I/O).

    For each bucket, keeps the row with the latest timestamp. Rows without
    a parseable timestamp are preserved as-is.
    """
    today = today or datetime.now(tz=timezone.utc).date()
    keep: dict[str, tuple[datetime, dict[str, Any]]] = {}
    orphans: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_snapshot_ts(row)
        if ts is None:
            orphans.append(row)
            continue
        bucket = _bucket_key(ts, today, policy)
        existing = keep.get(bucket)
        if existing is None or ts > existing[0]:
            keep[bucket] = (ts, row)
    kept = sorted(keep.values(), key=lambda pair: pair[0])
    return orphans + [row for _, row in kept]


def _atomic_replace_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False))
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        fsync_dir(path.parent)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def compact_snapshots(
    path: str | Path,
    *,
    policy: CompactionPolicy = DEFAULT_POLICY,
    today: date | None = None,
    keep_backup: bool = True,
) -> tuple[int, int]:
    """Rewrite ``path`` keeping only rows selected by ``policy``.

    Returns ``(rows_before, rows_after)``. Leaves a single ``.bak`` sibling
    if ``keep_backup`` is true.
    """
    p = Path(path)
    rows = load_jsonl(p)
    before = len(rows)
    kept = select_compacted(rows, policy=policy, today=today)
    if keep_backup and p.exists():
        backup = p.with_name(p.name + ".bak")
        shutil.copy2(p, backup)
    _atomic_replace_jsonl(p, kept)
    return before, len(kept)


def rotate_journal(
    path: str | Path,
    *,
    max_bytes: int = DEFAULT_ROTATE_BYTES,
    now: datetime | None = None,
) -> Path | None:
    """If ``path`` exceeds ``max_bytes``, move it aside and return the new name.

    The active file is renamed to ``<name>.<YYYYMMDDThhmmssZ>`` and a fresh
    (empty) active file is created in its place. Returns the archived path,
    or ``None`` if no rotation was needed.
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size < max_bytes:
        return None
    stamp = (now or datetime.now(tz=timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    archived = p.with_name(f"{p.name}.{stamp}")
    os.replace(p, archived)
    # Touch a fresh empty active file so callers see a stable path.
    p.touch()
    fsync_dir(p.parent)
    logger.info("rotated %s -> %s (%d bytes)", p, archived, archived.stat().st_size)
    return archived


def maybe_rotate(
    path: str | Path,
    *,
    max_bytes: int | None,
    now: datetime | None = None,
) -> Path | None:
    """Rotate when ``max_bytes`` is set and exceeded. No-op otherwise."""
    if not max_bytes or max_bytes <= 0:
        return None
    return rotate_journal(path, max_bytes=max_bytes, now=now)
