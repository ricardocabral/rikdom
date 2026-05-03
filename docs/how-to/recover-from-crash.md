# Recover from a crash or torn write

Rikdom's append-only journals use a trailing newline as a commit marker. A
crash mid-`append_jsonl` may leave a partial row without that newline. This
guide shows how to detect and recover. For the durability rules, see
[storage durability](../explanation/storage-durability.md).

## Read past a torn trailing line

The default reader path skips a torn tail with a warning:

```python
from rikdom.storage import load_jsonl
rows = load_jsonl("data/snapshots.jsonl")  # logs WARNING, returns clean rows
```

To truncate the torn tail on disk so the next append starts clean:

```python
load_jsonl("data/snapshots.jsonl", repair=True)
```

## Verify a journal

```python
from rikdom.journal import verify_journal
result = verify_journal("data/snapshots.jsonl")
# result.ok_rows, result.torn_tail_bytes, result.total_bytes
```

A nonzero `torn_tail_bytes` means a `repair=True` pass is warranted.

## Restore from backup

Every compaction leaves `<journal>.bak`. Rotation leaves
`<journal>.<timestamp>`. Both are plain JSONL and can be restored with a
simple copy:

```bash
cp data/snapshots.jsonl.bak data/snapshots.jsonl
```

After restoring, run `rikdom aggregate` and `rikdom viz` to confirm the
recovered state is usable.

## See also

- [Storage durability](../explanation/storage-durability.md)
- [Storage layout reference](../reference/storage-layout.md)
