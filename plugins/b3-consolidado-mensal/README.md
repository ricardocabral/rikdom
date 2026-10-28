# b3-consolidado-mensal

Plugin de importação dos relatórios de posição mensal e `Movimentação` da B3 em `.xlsx`.

## Entrada esperada

Arquivo Excel no formato de relatório consolidado mensal da B3, com abas de posição:
- `Posição - Ações` ou `Acoes`
- `Posição - BDR` ou `BDR`
- `Posição - ETF` ou `ETF`
- `Posição - Fundos` ou `Fundo de Investimento`
- `Posição - Renda Fixa` ou `Renda Fixa`
- `Posição - Tesouro Direto` ou `Tesouro Direto`

Os nomes antigos e atuais preservam a mesma identidade da posição. Um arquivo
com as duas variantes da mesma categoria é rejeitado para evitar escolher ou
somar posições ambíguas. O nome real da aba fica nos metadados de origem.

Também aceita a aba `Movimentação` com as colunas:

- `Entrada/Saída`
- `Data`
- `Movimentação`
- `Produto`
- `Instituição`
- `Quantidade`
- `Preço unitário`
- `Valor da Operação`

O perfil foi validado localmente contra uma exportação real autorizada. A
[fixture curta](fixtures/movimentacao_minimal/README.md) foi criada do zero,
com valores inteiramente fictícios. Nenhum dado ou metadado privado foi copiado.

Transferências de liquidação são normalizadas como compras/vendas; dividendos,
JCP e rendimentos preservam o valor informado. Transferências de custódia não
criam fluxos de caixa a partir de valores de avaliação. Eventos não suportados
ficam explícitos nos diagnósticos, sem inferir efeitos econômicos.

`Data` é preservada como data da movimentação, com precisão de dia e fuso
`America/Sao_Paulo`. O formato não estabelece por si só a data da negociação ou
liquidação, o número da conta, histórico completo, impostos ou valor bruto/líquido.
Essas informações não são inventadas. A instituição define somente um escopo
conservador de origem, não uma conta comprovada. A reconciliação de posições
permanece não computável até haver evidência compatível de conta, período e datas.

Para comparar uma posição verificada, prepare um JSON revisado para
`normalized-statement-json`, copiando a posição e as movimentações já armazenadas
com os mesmos IDs/chaves e metadados de origem. Confirme a vinculação à conta,
`as_of` da posição e a base `trade` ou `settled`. Na base `settled`, informe
`settled_at` com fuso; `effective_at` só pode substituí-lo quando a declaração
`effective_at_basis: "settled"` foi verificada explicitamente. A data de negociação
nunca substitui a liquidação. Movimentos com liquidação posterior a `as_of` ficam
fora da quantidade comparada.

Declare cobertura completa desde a origem e abertura zero somente com evidência
para isso; o primeiro movimento observado não comprova nenhuma dessas condições.
Não remova eventos não suportados nem infira datas, contas ou abertura zero.
Pré-visualize com `--dry-run --reconcile` antes de usar `--write --reconcile`.
O [passo a passo de revisão](../../docs/how-to/enter-and-correct-activities.md#review-b3-movimentação-evidence)
mostra os campos e comandos. Reutilize o JSON revisado: uma nova importação do
arquivo bruto pode substituir campos enriquecidos pelas observações originais.

Operações idênticas legítimas são preservadas separadamente. Reimportar o mesmo
arquivo ou reordenar suas linhas conserva as identidades. Exportações anônimas
sobrepostas são bloqueadas para [revisão explícita](../../docs/reference/import-diagnostics.md#reviewed-recovery).

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

Movement income whose reported amount does not establish gross/net now also emits
`metadata.rikdom_income = {"version": 1, "amount_basis": "unknown"}`. The existing
`amount_basis: reported_gross_net_unknown` evidence and source IDs are preserved.
Reimport or explicitly correct older canonical rows to add the neutral marker.
