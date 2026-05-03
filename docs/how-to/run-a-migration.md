# Run a schema migration

Use this guide to upgrade a `portfolio.json` or `policy.json` file to the
reader's current schema version. For the shipped versions and exit codes,
see the [migration version history reference](../reference/migrations.md).

## Preview first (dry-run)

Dry-run prints a JSON plan with every step the migrator would apply and the
per-step change log. No files are read beyond the input and no files are
written. **Run dry-run before every in-place upgrade.**

```bash
# Quick make shortcut (dry-run against sample portfolio)
make migrate-dry-run

# Preview against your workspace file
uv run rikdom migrate --portfolio data/portfolio.json --dry-run
```

For policy:

```bash
make migrate-dry-run-policy
uv run rikdom migrate-policy --policy data/policy.json --dry-run
```

## Migrate in place

This writes a sibling backup before overwriting (see
[Back up before a migration](back-up-before-migration.md)).

```bash
uv run rikdom migrate --portfolio data/portfolio.json
uv run rikdom migrate-policy --policy data/policy.json
```

## Migrate to a different file

Useful for staging upgrades. The source file is not modified and no backup
is written.

```bash
uv run rikdom migrate --portfolio data/portfolio.json --output data/portfolio.next.json
uv run rikdom migrate-policy --policy data/policy.json --output data/policy.next.json
```

## Pin a specific target version

```bash
uv run rikdom migrate --portfolio data/portfolio.json --to 1.1.0
uv run rikdom migrate-policy --policy data/policy.json --to 0.2.0
```

## Skip the backup sibling

Discouraged unless the file is under version control:

```bash
uv run rikdom migrate --portfolio data/portfolio.json --no-backup
uv run rikdom migrate-policy --policy data/policy.json --no-backup
```

## See also

- [Migration version history reference](../reference/migrations.md)
- [Back up before a migration](back-up-before-migration.md)
- [Author a new migration](author-a-migration.md)
