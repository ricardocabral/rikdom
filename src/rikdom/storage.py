from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def fsync_dir(path: str | Path) -> None:
    """Best-effort fsync of a directory so a rename is durable.

    On platforms where O_DIRECTORY or directory fsync is unsupported
    (e.g., Windows), this is a no-op.
    """
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except (OSError, NotImplementedError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, p)
        fsync_dir(p.parent)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def load_jsonl(
    path: str | Path,
    *,
    repair: bool = False,
) -> list[dict[str, Any]]:
    """Read a JSONL file, tolerating a torn trailing line.

    A crash mid-`append_jsonl` can leave a partial last line (no trailing
    newline, or an incomplete JSON object). By default such a tail is
    skipped with a warning. With ``repair=True`` the file is truncated on
    disk to the last complete line so subsequent appends start clean.
    """
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    last_good_end = 0
    with p.open("rb") as fb:
        raw_bytes = fb.read()
    offset = 0
    while offset < len(raw_bytes):
        nl = raw_bytes.find(b"\n", offset)
        if nl == -1:
            tail = raw_bytes[offset:].strip()
            if tail:
                logger.warning(
                    "skipping torn trailing line in %s (%d bytes, no newline)",
                    p,
                    len(tail),
                )
            break
        line_bytes = raw_bytes[offset:nl]
        offset = nl + 1
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            last_good_end = offset
            continue
        try:
            rows.append(json.loads(line))
            last_good_end = offset
        except json.JSONDecodeError as exc:
            logger.warning(
                "skipping malformed line in %s at offset %d: %s",
                p,
                offset - len(line_bytes) - 1,
                exc,
            )
            last_good_end = offset
    if repair and last_good_end != len(raw_bytes):
        with p.open("r+b") as fb:
            fb.truncate(last_good_end)
            fb.flush()
            os.fsync(fb.fileno())
        fsync_dir(p.parent)
    return rows


def append_jsonl(
    path: str | Path,
    row: dict[str, Any],
    *,
    durable: bool = True,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    data = line.encode("utf-8")
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
        if durable:
            os.fsync(fd)
    finally:
        os.close(fd)
    if durable:
        fsync_dir(p.parent)
