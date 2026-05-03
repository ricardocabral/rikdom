# Author a new migration

Use this guide when introducing a new shape into the portfolio or policy
schema. For the version history, see the
[migrations reference](../reference/migrations.md).

## Portfolio migration

1. Create `src/rikdom/migrations/vMAJOR_MINOR_PATCH_to_vMAJOR_MINOR_PATCH.py`.
2. Define a pure `_upgrade(portfolio) -> (new_portfolio, change_log)` function that:
   - works on a `copy.deepcopy` of the input (never mutates it),
   - touches only known keys,
   - leaves `metadata` / `extensions` / unknown top-level keys untouched,
   - is idempotent when re-run at the target version.
3. Export a `Migration` dataclass instance named `migration`.
4. Append it to `MIGRATIONS` in `src/rikdom/migrations/__init__.py`. The list
   must form a contiguous `from_version -> to_version` chain (enforced by
   `tests/test_migrations.py::PlannerTests::test_registry_is_contiguous_chain`).
5. Bump `CURRENT_SCHEMA_VERSION` in `src/rikdom/validate.py` and update the
   portfolio schema if the migration introduces new shapes.
6. Add a fixture and round-trip test under `tests/`.

## Policy migration

Same shape as the portfolio track, under `src/rikdom/migrations/policy/`:

1. Create `src/rikdom/migrations/policy/v0_X_0_to_v0_Y_0.py` with the same
   `_upgrade(policy) -> (new_policy, change_log)` contract.
2. Append the `migration` instance to `POLICY_MIGRATIONS` in
   `src/rikdom/migrations/policy/__init__.py` (contiguity enforced by
   `tests/test_policy_migrations.py::PlannerTests::test_registry_is_contiguous`).
3. Bump `CURRENT_POLICY_SCHEMA_VERSION` in `src/rikdom/policy.py` and update
   the policy schema at `src/rikdom/_resources/policy.schema.json` if shapes change.
4. Add a round-trip test under `tests/`.

## Idempotency check

Re-running a migration on a portfolio that is already at the target version
must be a no-op. The planner skips it, but the `_upgrade` function should
still tolerate target-shaped input — that property prevents corruption when
a chained migration replays an intermediate version.

## See also

- [Migration version history reference](../reference/migrations.md)
- [Run a schema migration](run-a-migration.md)
- [Back up before a migration](back-up-before-migration.md)
