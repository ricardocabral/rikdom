# Storage Durability

Rikdom keeps every piece of user state in plain-text, line-oriented files on
the local disk. That portability is only useful if those files survive a
crash, a full disk, or `Ctrl+C` at a bad moment. This document explains the
rules Rikdom follows and the reasoning behind them. For the recipe to
recover from a torn write, see
[recover from a crash](../how-to/recover-from-crash.md). For the file
inventory, see [storage layout](../reference/storage-layout.md).

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

## Why these rules

- **Atomic rename for whole documents** keeps `portfolio.json` valid at all
  times. A crash mid-write leaves the previous version untouched; readers
  never see a half-written file.
- **`O_APPEND` + newline-as-commit** for journals keeps appends safe under
  concurrent writers and makes torn rows trivially detectable.
- **`fsync` of the parent directory** is what makes the rename or append
  itself crash-safe; the bytes-on-platter rule only covers the file's
  contents otherwise.

## Compaction policy

`rikdom compact` rewrites a snapshots journal keeping only a policy-driven
subset. Defaults mirror the PRD guidance:

* **< 30 days old** — keep every snapshot (per-timestamp bucket).
* **30 days – 1 year** — keep one per ISO week (latest in bucket wins).
* **> 1 year** — keep one per calendar month.

Rows without a parseable `timestamp` are passed through untouched so nothing
is silently dropped. The rewrite is atomic: tempfile + `fsync` +
`os.replace` + directory fsync, so an interrupted compaction never corrupts
the journal.

For the commands and flags, see [CLI reference](../reference/cli.md#compaction).

## Rotation policy

Journals grow without bound by default. Rotation is opt-in per command via
`--rotate-bytes <N>`. Rotated files are never deleted by Rikdom — archive
or prune them yourself.

## What Rikdom will not do

- No opaque binary checkpoints. Everything stays `cat`-able.
- No cloud-hosted WAL. The filesystem is the durability boundary.
- No automatic deletion of archived or backup files. Retention is yours.

## See also

- [Recover from a crash](../how-to/recover-from-crash.md)
- [Storage layout reference](../reference/storage-layout.md)
- [CLI reference: compaction](../reference/cli.md#compaction)
