# Migração segura do histórico de IRPF

## Objetivo

Separar a declaração de IRPF do ano-calendário de 2025 da carteira ativa, preservando o histórico fiscal sem permitir que seus valores de fim de 2025 substituam posições correntes de 2026. Ao fim da migração, `make validate` deve validar as posições ativas sem erros causados por registros históricos incompletos.

## Fonte e escopo

A fonte é uma declaração de IRPF em XML. A carteira ativa pode conter posições atuais importadas de B3/BTG e registros históricos `irpf-*`; a importação direta pode substituir indevidamente os valores e a proveniência atuais.

## Desenho

### Arquivo histórico

A migração criará um artefato JSON específico do ano-calendário em `data/irpf-history/2025.json`. Ele conterá a data de referência, o caminho e o hash do XML de origem, e os itens normalizados pelo importador IRPF. Esse arquivo é somente histórico e não participa de agregação nem de validação da carteira ativa.

### Carteira ativa

Registros históricos cujo identificador começa com `irpf-` e cujo valor de mercado é zero serão removidos de `portfolio.json` depois de terem sido preservados no arquivo histórico. Registros de fonte IRPF que tenham valor não nulo permanecem como posições ativas; a migração acrescentará somente os atributos mínimos conhecidos, sem alterar valor, quantidade, data de referência, fonte atual ou outros metadados.

Os atributos que não podem ser determinados com segurança a partir da declaração ou do cadastro local receberão o valor explícito `OUTRO` apenas quando o catálogo exigir um tratamento tributário enumerado. A migração não inventará CNPJ de depositária, paridade de BDR, datas de emissão ou vencimento de títulos.

### Segurança e repetibilidade

O comando terá prévia por padrão e só escreverá com `--write`. Antes de escrever, ele criará backup atômico de `portfolio.json`; a execução repetida produzirá o mesmo arquivo histórico e não removerá posições correntes. A declaração XML nunca será copiada para o repositório nem adicionada ao Git.

## Componentes

- `scripts/migrate_irpf_history.py`: lê o XML pelo importador existente, cria o artefato histórico e poda somente registros históricos zerados.
- `tests/test_migrate_irpf_history.py`: cobre preservação de posição corrente, arquivamento de item IRPF, remoção segura e idempotência.
- `data/irpf-history/2025.json`: saída local gerada; permanece ignorada pelo Git porque `data/` já é local.

## Critérios de aceitação

1. A prévia informa os registros que seriam arquivados e removidos sem escrever arquivos.
2. A escrita preserva integralmente valores correntes e metadados de posições não históricas.
3. Os itens do XML ficam disponíveis no arquivo histórico com referência de origem verificável.
4. Nenhum registro `irpf-*` zerado permanece em `portfolio.json`.
5. A validação da carteira ativa não falha por atributos obrigatórios ausentes em registros históricos de IRPF.
