# b3-consolidado-mensal

Plugin de importação do relatório consolidado mensal da B3 em `.xlsx`.

## Entrada esperada

Arquivo Excel no formato de relatório consolidado mensal da B3, com abas de posição:
- `Posição - Ações`
- `Posição - BDR`
- `Posição - ETF`
- `Posição - Fundos`
- `Posição - Renda Fixa`
- `Posição - Tesouro Direto`

## Execução (CLI)

```bash
uv run rikdom import-statement \
  --portfolio data-sample/portfolio.json \
  --plugin b3-consolidado-mensal \
  --input /caminho/relatorio-consolidado-mensal.xlsx
```

## Execução (Pluggy)

```bash
uv run python - <<'PY'
from rikdom.plugin_engine.pipeline import run_import_pipeline

payload = run_import_pipeline(
    plugin_name="b3-consolidado-mensal",
    plugins_dir="plugins",
    input_path="/caminho/relatorio-consolidado-mensal.xlsx",
)
print(payload["provider"], len(payload["holdings"]))
PY
```
