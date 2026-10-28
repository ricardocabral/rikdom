# irpf-xml

`source/input` plugin that imports holdings from a Brazilian IRPF
(Imposto de Renda Pessoa Física) declaration XML produced by the SERPRO
desktop application.

## Input

`~/Documents/ProgramasRFB/IRPF<year>/aplicacao/dados/<cpf>/<cpf>-<id>.xml`

The plugin reads the `<bens>/<item>` ("Bens e Direitos") block and emits
one holding per item. All values are in BRL (IRPF reports year-end values
in BRL). Activities are not emitted.

## Run

```bash
uv run rikdom import-statement \
  --plugin irpf-xml --plugins-dir plugins \
  --input ~/Documents/ProgramasRFB/IRPF2026/aplicacao/dados/<cpf>/<cpf>-<id>.xml \
  --data-dir data --out-root out --dry-run
```

Add `--write` once the dry-run looks right.

## What gets imported

| Field | Source |
| --- | --- |
| `market_value` | `valorExercicioAtual` (current year-end), BRL |
| `metadata.value_current_year_end` / `value_prior_year_end` | both year-ends, BRL |
| `identifiers.ticker` | `codigoNegociacao` (B3 ticker) |
| `identifiers.cnpj` | `niEmpresa` (issuer / fund / bank CNPJ) |
| `identifiers.altcoin_code` / `stablecoin_code` | crypto codes |
| `metadata.account` | `banco` / `agencia` / `conta` for cash deposits |
| `metadata.irpf` | raw `grupo`, `codigo`, `indice`, `discriminacao`, country |

## Asset type mapping

`grupo`/`codigo` (and free-text hints in `discriminacao`) are mapped to
asset types from the default catalog and `asset-types-br-catalog`.
Highlights:

| IRPF (grupo, codigo) | `asset_type_id` |
| --- | --- |
| 01.* | `real_estate` |
| 02.* | `vehicle` |
| 03.01 / 03.02 | `acao` / `private_equity` |
| 04.02 | `fundo_investimento` |
| 04.03 + "TESOURO/CDB/LCI/LCA/CRA/CRI/DEBENT[ INFRA]" | `tesouro_direto` / `cdb` / `lci` / `lca` / `cra` / `cri` / `debenture[_infra]` |
| 04.04 (with ticker) | `bdr` |
| 06.* | `cash_equivalent` |
| 07.01 / 07.02 / 07.03 / 07.04 | `fundo_investimento` / `fiagro_cota` / `fii` / `fundo_investimento` |
| 99.06 | `previdencia_privada` |

Unmatched rows fall back to `other` so nothing is dropped silently.

## Holding IDs (cross-year dedup)

IDs are **year-agnostic** — `irpf-{grupo}{codigo}-<tag>-…` — so importing
`IRPF2025` and `IRPF2026` for the same CPF merges into one holding per
asset rather than duplicating. `<tag>` is recorded as
`metadata.irpf.id_strategy`:

| Tag | Strategy | Used when |
| --- | --- | --- |
| `tk` | `ticker` | `codigoNegociacao` is set |
| `alt` / `stb` | `altcoin_code` / `stablecoin_code` | crypto |
| `cnpj` | `issuer_cnpj` | mutual funds (07.*) |
| `acct` | `bank_account` | cash (06.*) — `cnpj + banco/agencia/conta + short discriminacao hash` |
| `h` | `discriminacao_hash` | fallback for real estate, vehicles, broker-held debt (04.03), JCP receivables |

The `{grupo}{codigo}` prefix prevents cross-bucket collisions (e.g., the
ITUB4 stock vs. a JCP-receivable on the same CNPJ).

### Caveats

- The `discriminacao_hash` fallback is brittle to text edits in the IRPF
  free-text field; the id changes if you edit the discriminacao.
- This plugin emits **point-in-time holdings**: importing IRPF2026 over
  IRPF2025 overwrites `market_value` with 2026 figures. For preserved
  historical year-ends, use `snapshots.jsonl`, not holdings.
- Cross-source dedup with non-IRPF importers is not automatic — see
  [Cross-importer deduplication](../../docs/explanation/cross-importer-dedup.md).

## Tests

```bash
cd plugins/irpf-xml && uv run python -m unittest tests.test_plugin
```

The contract suite (`tests.test_plugin_contracts`) also exercises this
plugin via `fixtures/sample/`.

## Privacy

The bundled fixture in `fixtures/sample/` is fully synthetic. **Never
commit a real declaration file** — IRPF XML contains CPF, names, account
numbers, and other sensitive PII.

## Received-income limit

This importer reads annual asset declarations as holdings, including declared
receivables. It does not emit posted dividend/interest activities or infer payment
dates, withholding, gross/net basis, cash availability or income completeness.
Import verified payments separately through `normalized-statement-json`.
