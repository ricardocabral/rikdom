# irpf-xml

Importer (`source/input` hook) for Brazilian IRPF (Imposto de Renda Pessoa
Física) declaration XML files produced by the SERPRO/Receita Federal IRPF
desktop application.

## What it imports

The plugin reads the `<bens>/<item>` block ("Bens e Direitos") and emits one
holding per item. For each item it captures:

- `market_value`: `valorExercicioAtual` (current year-end), in BRL
- `metadata.value_current_year_end` and `metadata.value_prior_year_end`:
  both year-end snapshots in BRL, so downstream tools can compare year over
  year
- `identifiers.cnpj`: parsed from `niEmpresa` (issuer / fund / bank CNPJ)
- `identifiers.ticker`: from `codigoNegociacao` (B3 ticker, when present)
- `identifiers.altcoin_code` / `stablecoin_code`: when the item is a crypto
  asset
- `metadata.irpf`: raw `grupo`, `codigo`, `indice`, `discriminacao`, country
  fields — preserved verbatim for auditability
- `metadata.account`: bank code, branch and account number for cash deposits

## Asset type mapping

`grupo` and `codigo` (and free-text hints in `discriminacao`) are mapped to
asset type ids from the default catalog and the `asset-types-br-catalog`
plugin. Highlights:

| IRPF (grupo, codigo) | rikdom `asset_type_id` |
| --- | --- |
| (01, *) | `real_estate` |
| (02, *) | `vehicle` |
| (03, 01) | `acao` |
| (03, 02) | `private_equity` |
| (04, 01) | `savings_account` |
| (04, 02) | `fundo_investimento` |
| (04, 03) "TESOURO" | `tesouro_direto` |
| (04, 03) "CDB" / "LCI" / "LCA" | `cdb` / `lci` / `lca` |
| (04, 03) "CRA" / "CRI" | `cra` / `cri` |
| (04, 03) "DEBENT … INFRA" | `debenture_infra` |
| (04, 03) "DEBENT" | `debenture` |
| (04, 04) ticker present | `bdr` |
| (06, *) | `cash_equivalent` |
| (07, 01 / 04) | `fundo_investimento` |
| (07, 02) | `fiagro_cota` |
| (07, 03) | `fii` |
| (99, 06) | `previdencia_privada` |

Anything that does not match a known mapping is emitted as `other` so the
holding is preserved and can be reclassified later.

## Run it

```bash
uv run rikdom import-statement \
  --plugin irpf-xml \
  --plugins-dir plugins \
  --input ~/Documents/ProgramasRFB/IRPF2026/aplicacao/dados/<cpf>/<cpf>-0000000000.xml \
  --data-dir data --out-root out \
  --dry-run
```

Add `--write` once the dry run looks good.

## Tests

```bash
cd plugins/irpf-xml
uv run python -m unittest tests.test_plugin
```

The contract suite (`tests.test_plugin_contracts`) also exercises this
plugin via `fixtures/sample/`.

## Notes / caveats

- IRPF reports all values in BRL (year-end FX); the plugin emits BRL.
- Foreign-country items (`pais != 105`) are still emitted, but no ISO
  alpha-2 country is set on `jurisdiction` — only the raw IRPF country
  code/label is preserved in `metadata.irpf` (IRPF uses a numeric country
  table that does not map 1:1 to ISO 3166).
- Quantities are not parsed from `discriminacao` free text — the IRPF XML
  does not expose a structured quantity field for most asset classes.
- The fixture file in `fixtures/sample/` is fully synthetic. **Do not
  commit real declaration data** — IRPF files contain CPFs, names, account
  numbers, and other sensitive PII.
