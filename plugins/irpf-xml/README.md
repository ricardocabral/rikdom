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

## Holding IDs and cross-year dedup

The plugin mints **year-agnostic stable holding ids** so that importing
multiple consecutive declarations (e.g., IRPF2025 then IRPF2026) merges
into a single holding per asset rather than creating duplicates. Rikdom's
merge pass keys off the top-level `id`, so getting the id derivation right
is what makes cross-year imports idempotent.

Each id is `irpf-{grupo}{codigo}-<tag>-...` where `<tag>` records which
field was used to derive the id (also stored as `metadata.irpf.id_strategy`):

| Tag | Strategy | Used when |
| --- | --- | --- |
| `tk` | `ticker` | `codigoNegociacao` is set (acao, fii, etf, bdr) |
| `alt` / `stb` | `altcoin_code` / `stablecoin_code` | crypto entries with explicit codes |
| `cnpj` | `issuer_cnpj` | mutual funds (group 07.*) — fund CNPJ uniquely identifies the fund |
| `acct` | `bank_account` | cash deposits (group 06.*) — `cnpj + banco/agencia/conta + short discriminacao hash` |
| `h` | `discriminacao_hash` | everything else (real estate, vehicles, broker-held debt, JCP receivables) — deterministic blake2s of `(grupo, codigo, cnpj, normalized discriminacao)` |

Why the prefix includes both `grupo` and `codigo`: the same legal entity
can appear in multiple IRPF buckets (e.g., ITUB4 stock in `03.01` and a
JCP-receivable on the same CNPJ in `99.07`). Without the bucket prefix
they would collide.

### Caveats

- The `discriminacao_hash` fallback is **brittle against text edits**.
  If you edit the free-text `discriminacao` between years (e.g., adjust
  acquisition-history notes), the id changes and the plugin can no longer
  match the prior year's holding. Affected groups: `01.*` (real estate),
  `02.*` (vehicles), `04.03` (broker-held public/private debt), `99.07`
  (JCP receivables). For these, prefer a transactional source plugin if
  available.
- The plugin emits **point-in-time holdings** for the most recent year.
  Importing IRPF2026 after IRPF2025 will overwrite the holding's
  `market_value` and `metadata.value_*_year_end` with 2026 figures. Use
  `snapshots.jsonl` (a different stream) if you need preserved
  historical year-end values.
- Mixing this importer with a transactional source (CSV / B3) will not
  cross-dedup automatically — those importers mint their own ids. Use
  IRPF as a year-end bootstrap and switch to the transactional source for
  ongoing tracking, or write a downstream `enrichment`/`transform`
  plugin that collapses by `(asset_type_id, identifiers.cnpj,
  identifiers.ticker)`.

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
