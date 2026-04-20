# asset-types-br-catalog

Pluggy `asset-type/catalog` plugin with Brazilian asset-type definitions for fixed income, funds, listed wrappers, and structured products.

## Included Asset Types

- `acao`
- `bdr`
- `etf`
- `fii`
- `tesouro_direto`
- `cdb`
- `lci`
- `lca`
- `lig`
- `lf`
- `cri`
- `cra`
- `debenture`
- `debenture_incentivada` (Lei 12.431, investor IR isento)
- `debenture_infra` (Lei 14.801, issuer benefit, investor IR regressivo)
- `coe`
- `fundo_investimento`
- `fidc_cota`
- `fiagro_cota`
- `previdencia_privada` (PGBL/VGBL)

## Asset Classes Used

- `real_estate`: `fii`
- `debt`: `tesouro_direto`, `cdb`, `lci`, `lca`, `lig`, `lf`, `cri`, `cra`, `debenture`, `debenture_incentivada`, `debenture_infra`
- `stocks`: `acao`, `bdr`
- `other`: `coe`
- `funds`: `etf`, `fundo_investimento`, `fidc_cota`, `fiagro_cota`, `previdencia_privada`

## Validations Encoded In Catalog Definitions

These validations are provided by the catalog metadata and are consumed by `rikdom` validation rules for declared instrument attributes.

- Required instrument attributes per asset type (for example `issuer_cnpj`, `indexer`, `maturity_date` where applicable)
- Value type constraints (`string`, `integer`, `number`, `boolean`)
- Enum constraints for canonical fields (for example `indexer`, `remuneration_type`, `bdr_level`, `modalidade`, `subclass_type`)
- Pattern metadata for Brazil identifiers:
  - CNPJ: `^\d{14}$`
  - ISIN (BR): `^BR[A-Z0-9]{9}\d$`
  - B3 ticker: `^[A-Z]{4}\d{2}[A-Z]?$`

## How To Use

1. Confirm the plugin is installed and discoverable:

```bash
uv run rikdom plugins list --plugins-dir plugins
```

2. Build and inspect the effective asset-type catalog:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run python - <<'PY'
import json
from rikdom.plugin_engine.pipeline import build_asset_type_catalog

catalog = build_asset_type_catalog("plugins")
print(json.dumps(catalog, indent=2, ensure_ascii=False))
PY
```

3. Use the generated catalog entries in `portfolio.asset_type_catalog` before validating/importing holdings that reference these `asset_type_id` values.

4. Validate your portfolio:

```bash
uv run rikdom validate --portfolio data/portfolio.json
```
