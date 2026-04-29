# Schema Migrations

Rikdom maintains two independent schema tracks, each evolved under its own semver:

- **Portfolio** — `CURRENT_SCHEMA_VERSION` in `src/rikdom/validate.py`, upgraded by
  `rikdom migrate`.
- **Policy** (Investment Policy Statement) — `CURRENT_POLICY_SCHEMA_VERSION` in
  `src/rikdom/policy.py`, upgraded by `rikdom migrate-policy`.

Both files are long-lived JSON; migrations move them forward while preserving unknown
user data under `metadata` / `extensions`.

## Version history

### Portfolio

| from → to | summary |
| --- | --- |
| 1.0.0 → 1.1.0 | optional `activities[]` ledger |
| 1.1.0 → 1.2.0 | optional `operations` (task catalog/events) slot |
| 1.2.0 → 1.3.0 | optional `liabilities[]`, `tax_lots[]`, `holdings[].account_id` |
| 1.3.0 → 1.4.0 | expanded `activities[].event_type` (merger, contribution, withdrawal, tax_withheld, fx_conversion) and optional `account_id`, `holding_id`, `tax_lot_ids`, `withholding_tax`, `realized_gain`, `fx_rate`, `counter_money` |

### Policy

| from → to | summary |
| --- | --- |
| 0.1.0 → 0.2.0 | optional `benchmarks[]` registry + `benchmark_id` on allocation targets |
| 0.2.0 → 0.3.0 | optional `tax_rules[]` and `tax_exemptions[]` tables |

## Compatibility policy

- Readers accept any `schema_version` within the current major, between
  `MIN_COMPATIBLE_SCHEMA_VERSION` and `CURRENT_SCHEMA_VERSION`.
- `schema_uri` must match the canonical URI
  (`https://example.org/rikdom/schema/portfolio.schema.json`).
- Unknown fields under `metadata` and top-level `extensions` are preserved across migrations.
- Downgrades are **not supported**. If you need an older shape, restore from backup.

## CLI

### Portfolio

```bash
# Quick make shortcut (dry-run against sample portfolio)
make migrate-dry-run

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

### Policy

The policy track mirrors the portfolio CLI; flags are identical except the file
argument is `--policy`.

```bash
# Dry-run against sample policy
make migrate-dry-run-policy

# Preview / migrate in place / pin a target version
uv run rikdom migrate-policy --policy data/policy.json --dry-run
uv run rikdom migrate-policy --policy data/policy.json
uv run rikdom migrate-policy --policy data/policy.json --to 0.2.0
uv run rikdom migrate-policy --policy data/policy.json --output data/policy.next.json
uv run rikdom migrate-policy --policy data/policy.json --no-backup
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

### Portfolio

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

### Policy

Same shape as the portfolio track, under `src/rikdom/migrations/policy/`:

1. Create `src/rikdom/migrations/policy/v0_X_0_to_v0_Y_0.py` with the same
   `_upgrade(policy) -> (new_policy, change_log)` contract.
2. Append the `migration` instance to `POLICY_MIGRATIONS` in
   `src/rikdom/migrations/policy/__init__.py` (contiguity enforced by
   `tests/test_policy_migrations.py::PlannerTests::test_registry_is_contiguous`).
3. Bump `CURRENT_POLICY_SCHEMA_VERSION` in `src/rikdom/policy.py` and update the
   policy schema at `src/rikdom/_resources/policy.schema.json` if shapes change.
4. Add a round-trip test under `tests/`.

## Known limits

- No downgrade path; restore from backup.
- `migrate` refuses to run on structurally invalid portfolios. Fields validated as part of
  schema-compat (`schema_version`, `schema_uri`) are exempt from this gate because fixing
  them is migration's job. A future `--force` flag may relax the structural gate when a
  migration is explicitly designed to repair invalid input.
