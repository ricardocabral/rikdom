# Schema Migrations

Rikdom portfolios are long-lived JSON files. As the canonical schema evolves under semver
(`CURRENT_SCHEMA_VERSION` in `src/rikdom/validate.py`), the `rikdom migrate` command upgrades
older files forward while preserving unknown user data.

## Compatibility policy

- Readers accept any `schema_version` within the current major, between
  `MIN_COMPATIBLE_SCHEMA_VERSION` and `CURRENT_SCHEMA_VERSION`.
- `schema_uri` must match the canonical URI
  (`https://example.org/rikdom/schema/portfolio.schema.json`).
- Unknown fields under `metadata` and top-level `extensions` are preserved across migrations.
- Downgrades are **not supported**. If you need an older shape, restore from backup.

## CLI

```bash
# Preview a migration without writing anything
uv run rikdom migrate --portfolio data/portfolio.json --dry-run

# Migrate in place to the reader's current version, with sibling backup
uv run rikdom migrate --portfolio data/portfolio.json

# Migrate into a different file (no in-place write, no backup)
uv run rikdom migrate --portfolio data/portfolio.json --output data/portfolio.next.json

# Skip the backup sibling (discouraged unless the file is under version control)
uv run rikdom migrate --portfolio data/portfolio.json --no-backup

# Pin a specific target version
uv run rikdom migrate --portfolio data/portfolio.json --to 1.1.0
```

Exit codes:
- `0` — success (including no-op when already at target)
- `1` — invalid portfolio, invalid target, no migration path, or post-validation failure

## Dry run

Dry-run prints a JSON plan with every step the migrator would apply and the per-step change
log. No files are read beyond the input and no files are written. Use it before every in-place
upgrade.

## Backup strategy

Before overwriting a portfolio in place, `migrate` writes a sibling backup named
`<portfolio>.bak-YYYYMMDDTHHMMSSZ` (UTC). To roll back, replace the file with the backup:

```bash
mv data/portfolio.json.bak-20260420T153000Z data/portfolio.json
```

Backups are skipped when:
- `--no-backup` is passed (use only when the file is under version control), or
- `--output <path>` is passed (the source is not modified).

On top of automatic backups, keep portfolio files under version control (git) so that every
migration lands as an auditable commit.

## Authoring a new migration

1. Create `src/rikdom/migrations/vMAJOR_MINOR_PATCH_to_vMAJOR_MINOR_PATCH.py`.
2. Define a pure `_upgrade(portfolio) -> (new_portfolio, change_log)` function that:
   - works on a `copy.deepcopy` of the input (never mutates it),
   - touches only known keys,
   - leaves `metadata` / `extensions` / unknown top-level keys untouched,
   - is idempotent when re-run at the target version.
3. Export a `Migration` dataclass instance named `migration`.
4. Append it to `MIGRATIONS` in `src/rikdom/migrations/__init__.py`. The list must form a
   contiguous `from_version -> to_version` chain (enforced by
   `tests/test_migrations.py::PlannerTests::test_registry_is_contiguous_chain`).
5. Bump `CURRENT_SCHEMA_VERSION` in `src/rikdom/validate.py` and update the `portfolio`
   schema if the migration introduces new shapes.
6. Add a fixture and round-trip test under `tests/`.

## Known limits

- No downgrade path; restore from backup.
- `migrate` refuses to run on structurally invalid portfolios. Fields validated as part of
  schema-compat (`schema_version`, `schema_uri`) are exempt from this gate because fixing
  them is migration's job. A future `--force` flag may relax the structural gate when a
  migration is explicitly designed to repair invalid input.
