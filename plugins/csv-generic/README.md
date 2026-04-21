# csv-generic

Pluggy `source/input` plugin that imports holdings and activities from a generic CSV statement.

## Entrada esperada

CSV com cabeçalho. Cada linha é interpretada por `record_type`:
- `holding` (padrão): gera item em `holdings`
- `activity`: gera item em `activities`

Campos principais para `holding`:
- obrigatórios: `id`, `asset_type_id`, `label`, `amount`, `currency`
- opcionais: `quantity`, `ticker`, `country`, `fx_rate_to_base`

Campos principais para `activity`:
- obrigatórios: `id`, `amount`, `currency`
- opcionais: `event_type`, `effective_at`, `status`, `asset_type_id`, `subtype`, `quantity`, `ticker`, `country`, `idempotency_key`, `source_ref`

## Execução (CLI)

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
