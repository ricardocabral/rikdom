# Migration Version History

Rikdom maintains two independent schema tracks, each evolved under its own semver:

- **Portfolio** — `CURRENT_SCHEMA_VERSION` in `src/rikdom/validate.py`, upgraded by
  `rikdom migrate`.
- **Policy** (Investment Policy Statement) — `CURRENT_POLICY_SCHEMA_VERSION` in
  `src/rikdom/policy.py`, upgraded by `rikdom migrate-policy`.

Both files are long-lived JSON; migrations move them forward while preserving
unknown user data under `metadata` / `extensions`.

## Portfolio version history

| from → to | summary |
| --- | --- |
| 1.0.0 → 1.1.0 | optional `activities[]` ledger |
| 1.1.0 → 1.2.0 | optional `operations` (task catalog/events) slot |
| 1.2.0 → 1.3.0 | optional `liabilities[]`, `tax_lots[]`, `holdings[].account_id` |
| 1.3.0 → 1.4.0 | expanded `activities[].event_type` (merger, contribution, withdrawal, tax_withheld, fx_conversion) and optional `account_id`, `holding_id`, `tax_lot_ids`, `withholding_tax`, `realized_gain`, `fx_rate`, `counter_money` |
| 1.4.0 → 1.5.0 | optional `Money.fx_ref` (`as_of_date`, `base_currency`, `quote_currency`, `rate_to_base`, `source`) for line-item FX provenance |
| 1.5.0 → 1.6.0 | optional `trade_at`, `settled_at`, signed `cost_basis_adjustment`, structured `corporate_action` legs, `amortization` events and `holdings[].extensions.rikdom_instrument_history`; migration changes only the version and preserves asserted history without inventing dates or basis |
| 1.6.0 → 1.7.0 | optional reported statement observations, holding valuation and acquisition observations, and indexer multipliers; migration only advances the version and never infers transactions or tax basis |

## Policy version history

| from → to | summary |
| --- | --- |
| 0.1.0 → 0.2.0 | optional `benchmarks[]` registry + `benchmark_id` on allocation targets |
| 0.2.0 → 0.3.0 | optional `tax_rules[]` and `tax_exemptions[]` tables |

## Compatibility policy

- Correction-aware financial readers accept compatible legacy 1.x versions
  through 1.7.0 and exact version 2.0.0. Correction-bearing portfolios require
  2.0.0. The first correction writes that version with its linked event; it is
  not a generic migration step. See [activity corrections](../how-to/enter-and-correct-activities.md#correct-an-existing-event).
- `schema_uri` must match the canonical URI
  (`https://example.org/rikdom/schema/portfolio.schema.json`).
- Unknown fields under `metadata` and top-level `extensions` are preserved
  across migrations.
- Downgrades are **not supported**. If you need an older shape, restore from backup.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success (including no-op when already at target). |
| `1` | Invalid portfolio, invalid target, no migration path, or post-validation failure. |

## Known limits

- No downgrade path; restore from backup.
- `migrate` refuses to run on structurally invalid portfolios. Fields validated
  as part of schema-compat (`schema_version`, `schema_uri`) are exempt because
  fixing them is migration's job. A future `--force` flag may relax the
  structural gate when a migration is explicitly designed to repair invalid input.

## See also

- [Run a migration](../how-to/run-a-migration.md)
- [Author a new migration](../how-to/author-a-migration.md)
- [Back up before a migration](../how-to/back-up-before-migration.md)
