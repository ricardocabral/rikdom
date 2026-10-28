# csv-generic

Pluggy `source/input` plugin that imports holdings and activities from a generic CSV statement.

## Entrada esperada

CSV com cabeçalho. Cada linha é interpretada por `record_type`:
- `holding` (padrão): gera item em `holdings`
- `activity`: gera item em `activities`

Campos principais para `holding`:
- obrigatórios: `id`, `asset_type_id`, `label`, `amount`, `currency`
- opcionais: `quantity`, `ticker`, `country`, `fx_rate_to_base` (compatibilidade legada; o fluxo padrão usa histórico FX nativo)

Campos principais para `activity`:
- obrigatórios: `id`, `amount`, `currency`
- opcionais: `event_type`, `effective_at`, `status`, `asset_type_id`, `subtype`, `quantity`, `ticker`, `country`, `idempotency_key`, `source_ref`

## Execução (CLI)

Atalho no root do repositório (usa fixture de exemplo e persiste import):

```bash
make import-sample
```

Comando completo:

```bash
uv run rikdom import-statement \
  --plugin csv-generic \
  --input data-sample/sample_statement.csv \
  --portfolio data-sample/portfolio.json
```

## Execução (Pluggy)

```bash
uv run python - <<'PY'
from rikdom.plugin_engine.pipeline import run_import_pipeline

payload = run_import_pipeline(
    plugin_name="csv-generic",
    plugins_dir="plugins",
    input_path="data-sample/sample_statement.csv",
)
print(payload["provider"], len(payload.get("holdings", [])), len(payload.get("activities", [])))
PY
```

## Canonical income evidence

This is a caller-normalized input, not a broker label mapper. Supply canonical
`event_type` (`dividend`, `interest`, `income`, `tax_withheld`, etc.) and signed
`amount` yourself. `effective_at` is required for activities.

For income, optional `amount_basis` accepts `gross`, `net` or `unknown` and emits
`metadata.rikdom_income` version 1. If omitted, the canonical schema's existing
gross-amount convention remains in effect. Use `unknown` when source evidence
does not establish gross/net; do not treat an ambiguous provider cash amount as
gross merely because it can fit this CSV.

Optional `withholding_tax` and `fees` carry signed finite amounts, including
explicit zero. Optional `withholding_tax_currency` and `fees_currency` retain
each charge's own currency; omitted charge currencies mean the row's canonical
`currency`. Missing charge amounts stay absent. Invalid supplied amounts, basis
or charge currencies are rejected. Separate `tax_withheld` rows are not counted
as dividends and are not automatically linked to income.

IDs and idempotency keys are caller-controlled. For immutable corrections,
source identity evidence or richer metadata, use reviewed
[normalized JSON](../normalized-statement-json/README.md).
