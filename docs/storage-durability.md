# Storage Durability

Rikdom keeps every piece of user state in plain-text, line-oriented files on
the local disk. That portability is only useful if those files survive a
crash, a full disk, or `Ctrl+C` at a bad moment. This document states the
rules Rikdom follows, the journal files it writes, and how to recover when
something goes wrong.

## Write rules

### Canonical JSON (`save_json`)

Used for `data/portfolio.json` and any other "whole document" state.

1. Write the full JSON to a sibling temp file in the same directory.
2. `flush()` + `os.fsync(fd)` to push bytes past the OS cache.
3. `os.replace(tmp, target)` — atomic on POSIX and Windows.
4. `fsync` the containing directory so the rename itself is durable
   (best-effort; no-op on platforms that don't support it).

If any step fails, the temp file is removed and the original file is left
untouched. There is no window in which a reader can observe a half-written
portfolio.

### Append-only journals (`append_jsonl`)

Used for `data/snapshots.jsonl` and `data/import_log.jsonl`.

1. Open the file in append mode with `O_APPEND` (atomic append on POSIX).
2. Write exactly one UTF-8 JSON object followed by `\n`.
3. `fsync(fd)` before returning so the row is on disk.
4. `fsync` the parent directory.

The trailing newline is the **commit marker**. A row without a newline is
treated as torn and is skipped by readers.

`append_jsonl(..., durable=False)` skips the fsyncs for high-frequency
callers that accept a shorter durability window (none in core today).

## Journal inventory

| File                      | Kind          | Written by                         |
| ------------------------- | ------------- | ---------------------------------- |
| `data/portfolio.json`     | Whole doc     | `import-statement --write`, `migrate` |
| `data/snapshots.jsonl`    | Append-only   | `snapshot`                         |
| `data/import_log.jsonl`   | Append-only   | `import-statement`                 |

Journals are line-oriented JSONL. One row per line, UTF-8, LF terminator.
No CRLF. No header.

## Rotation policy

Journals grow without bound by default. Rotation is opt-in per-command.

* `rikdom snapshot --rotate-bytes 16777216` rotates
  `data/snapshots.jsonl` when it exceeds 16 MiB, moving it aside to
  `data/snapshots.jsonl.<YYYYMMDDThhmmssZ>` and starting a fresh active file.
* `rikdom compact --rotate --rotate-bytes <N>` does the same on demand.
  Without `--rotate-bytes` the rotation is always applied.

Rotated files are never deleted by Rikdom. Archive or prune them yourself.

## Compaction policy

`rikdom compact` rewrites a snapshots journal keeping only a policy-driven
subset. Defaults mirror the PRD guidance:

* **< 30 days old** — keep every snapshot (per-timestamp bucket).
* **30 days – 1 year** — keep one per ISO week (latest in bucket wins).
* **> 1 year** — keep one per calendar month.

Rows without a parseable `timestamp` are passed through untouched so nothing
is silently dropped.

### Running it

```bash
# Plan only (no write).
uv run rikdom compact --snapshots data/snapshots.jsonl --dry-run

# Apply. Leaves data/snapshots.jsonl.bak as a one-cycle safety net.
uv run rikdom compact --snapshots data/snapshots.jsonl

# Custom retention.
uv run rikdom compact --daily-days 60 --weekly-days 730

# Rotate aside first, then compact the new (empty) active file.
uv run rikdom compact --rotate
```

The rewrite is atomic: tempfile + `fsync` + `os.replace` + directory fsync,
so an interrupted compaction never corrupts the journal.

## Recovery workflow

### Torn trailing line

A crash mid-`append_jsonl` may leave a partial row without its commit
newline. The default reader path skips it with a warning:

```python
from rikdom.storage import load_jsonl
rows = load_jsonl("data/snapshots.jsonl")     # logs WARNING, returns clean rows
```

To truncate the torn tail on disk so the next append starts clean:

```python
load_jsonl("data/snapshots.jsonl", repair=True)
```

### Verifying a journal

```python
from rikdom.journal import verify_journal
result = verify_journal("data/snapshots.jsonl")
# result.ok_rows, result.torn_tail_bytes, result.total_bytes
```

Nonzero `torn_tail_bytes` means a repair pass is warranted.

### Restoring from backup

Every compaction leaves `<journal>.bak`. Rotation leaves
`<journal>.<timestamp>`. Both are plain JSONL and can be restored with a
simple copy:

```bash
cp data/snapshots.jsonl.bak data/snapshots.jsonl
```

After restoring, run `rikdom aggregate` and `rikdom viz` to confirm
the recovered state is usable.

## What Rikdom will not do

* No opaque binary checkpoints. Everything stays `cat`-able.
* No cloud-hosted WAL. The filesystem is the durability boundary.
* No automatic deletion of archived or backup files. Retention is yours.
