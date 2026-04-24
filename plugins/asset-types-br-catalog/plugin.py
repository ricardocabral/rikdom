from __future__ import annotations

from rikdom.plugin_engine.contracts import (
    BRAZIL_B3_TICKER_REGEX,
    BRAZIL_CNPJ_REGEX,
    BRAZIL_INDEXER_ENUM,
    BRAZIL_ISIN_REGEX,
)
from rikdom.plugin_engine.hookspecs import hookimpl


_REMUNERATION_ENUM = ["PREFIXADO", "POS", "HIBRIDO"]
_IR_PF_TREATMENT_ENUM = ["ISENTO", "REGRESSIVO", "PROGRESSIVO", "ALIQUOTA_FIXA", "OUTRO"]
_BDR_LEVEL_ENUM = ["N1_NAO_PATROCINADO", "N1_PATROCINADO", "N2_PATROCINADO", "N3_PATROCINADO"]
_COE_MODALIDADE_ENUM = ["VALOR_NOMINAL_PROTEGIDO", "VALOR_NOMINAL_EM_RISCO"]
_FIDC_SUBCLASS_ENUM = ["SENIOR", "SUBORDINADA_MEZANINO", "SUBORDINADA_JUNIOR"]
_FIDC_TARGET_INVESTOR_ENUM = ["VAREJO", "QUALIFICADO", "PROFISSIONAL"]
_OPEN_CLOSED_ENUM = ["ABERTO", "FECHADO"]
_TARGET_CHAIN_ENUM = ["CADEIA_AGRO"]
_FIAGRO_STRATEGY_ENUM = ["TERRA", "FIDC_LIKE", "FIP_LIKE", "MULTI"]
_FII_TYPE_ENUM = ["TIJOLO", "PAPEL", "HIBRIDO", "FOF", "DESENVOLVIMENTO"]
_ACAO_SHARE_CLASS_ENUM = ["ON", "PN", "PNA", "PNB", "UNIT"]
_ETF_UNDERLYING_CLASS_ENUM = ["RENDA_VARIAVEL", "RENDA_FIXA", "CRIPTO", "COMMODITIES", "INTERNACIONAL"]
_FUND_CATEGORY_ENUM = [
    "RENDA_FIXA",
    "MULTIMERCADO",
    "ACOES",
    "CAMBIAL",
    "FIC",
    "FIDC",
    "PREVIDENCIARIO",
]
_PREV_PLAN_TYPE_ENUM = ["PGBL", "VGBL"]
_PREV_REGIME_ENUM = ["PROGRESSIVO", "REGRESSIVO"]
_DEBENTURE_REGIME_ENUM = ["NAO_INCENTIVADA", "LEI_12431", "LEI_14801"]
_ISO_3166_ALPHA2_REGEX = r"^[A-Z]{2}$"
_ISIN_REGEX = r"^[A-Z]{2}[A-Z0-9]{9}\d$"


def _attr(
    attr_id: str,
    label: str,
    value_type: str,
    *,
    required: bool,
    enum: list[str] | None = None,
    pattern: str | None = None,
) -> dict:
    item = {
        "id": attr_id,
        "label": label,
        "value_type": value_type,
        "required": required,
    }
    if enum:
        # Copy to avoid cross-asset mutation when consumers edit metadata in place.
        item["enum"] = list(enum)
    if pattern:
        item["pattern"] = pattern
    return item


def _attrs_credit_letter_or_debenture() -> list[dict]:
    return [
        _attr("issuer_cnpj", "Issuer CNPJ", "string", required=True, pattern=BRAZIL_CNPJ_REGEX),
        _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
        _attr("issue_date", "Issue Date", "string", required=True),
        _attr("maturity_date", "Maturity Date", "string", required=True),
        _attr("remuneration_type", "Remuneration Type", "string", required=True, enum=_REMUNERATION_ENUM),
        _attr("indexer", "Indexer", "string", required=True, enum=BRAZIL_INDEXER_ENUM),
        _attr("spread_pct", "Spread (%)", "number", required=False),
        _attr("spread_bps", "Spread (bps)", "integer", required=False),
        _attr("amortization_schedule", "Amortization Schedule", "string", required=False),
        _attr("interest_schedule", "Interest Schedule", "string", required=False),
        _attr(
            "tax_profile.ir_pf_treatment",
            "Tax Profile: IR PF Treatment",
            "string",
            required=True,
            enum=_IR_PF_TREATMENT_ENUM,
        ),
        _attr(
            "tax_profile.source_rule_ref",
            "Tax Profile: Source Rule Reference",
            "string",
            required=False,
        ),
    ]


def _etf_attrs(*, underlying_class: str) -> list[dict]:
    """Return ETF instrument attributes pre-filled with the known underlying_class enum."""
    return [
        _attr("b3_ticker", "B3 Ticker", "string", required=True, pattern=BRAZIL_B3_TICKER_REGEX),
        _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
        _attr("fund_cnpj", "Fund CNPJ", "string", required=False, pattern=BRAZIL_CNPJ_REGEX),
        _attr(
            "underlying_class",
            "Underlying Asset Class",
            "string",
            required=True,
            enum=[underlying_class],
        ),
        _attr("benchmark_index", "Benchmark Index", "string", required=False),
        _attr(
            "tax_profile.ir_pf_treatment",
            "Tax Profile: IR PF Treatment",
            "string",
            required=True,
            enum=_IR_PF_TREATMENT_ENUM,
        ),
    ]


def _known_br_etfs() -> list[dict]:
    """Specialised B3 ETF asset types with pre-filled economic_exposure.

    Brokers and exchanges classify every listed ETF as 'stocks' for trading
    purposes, which distorts economic risk analysis for bond, REIT, or
    commodity ETFs. These entries declare the look-through exposure so
    agents can analyse the portfolio against the user's IPS dimensions
    (asset_class, region, currency, factor, duration) without being fooled
    by the wrapper. Holdings may override via holding.economic_exposure.
    Source: public issuer factsheets and prospectuses as of 2026-04.
    """
    return [
        {
            "id": "etf_ivvb11",
            "label": "ETF IVVB11 (S&P 500 via iShares BR)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="INTERNACIONAL"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "notes": "Unhedged exposure to S&P 500; BRL-quoted shares with USD-denominated underlying.",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "stocks",
                        "region": "US",
                        "currency": "USD",
                        "factor": "broad_market",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_bova11",
            "label": "ETF BOVA11 (Ibovespa via iShares BR)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="RENDA_VARIAVEL"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "stocks",
                        "region": "BR",
                        "currency": "BRL",
                        "factor": "broad_market",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_smal11",
            "label": "ETF SMAL11 (Small Caps BR via iShares)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="RENDA_VARIAVEL"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "stocks",
                        "region": "BR",
                        "currency": "BRL",
                        "factor": "size_small",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_divo11",
            "label": "ETF DIVO11 (Dividendos BR)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="RENDA_VARIAVEL"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "stocks",
                        "region": "BR",
                        "currency": "BRL",
                        "factor": "value",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_fixa11",
            "label": "ETF FIXA11 (Renda Fixa Prefixada IRF-M)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="RENDA_FIXA"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "notes": "Tracked as stock at the broker, but economically Brazilian sovereign prefixed debt.",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "debt",
                        "region": "BR",
                        "currency": "BRL",
                        "duration": "intermediate",
                        "factor": "sovereign_prefixed",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_imab11",
            "label": "ETF IMAB11 (Renda Fixa IMA-B inflação)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="RENDA_FIXA"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "notes": "Brazilian inflation-linked (NTN-B) sovereign debt.",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "debt",
                        "region": "BR",
                        "currency": "BRL",
                        "duration": "long",
                        "factor": "sovereign_inflation_linked",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_b5p211",
            "label": "ETF B5P211 (Tesouro Selic curto)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="RENDA_FIXA"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "debt",
                        "region": "BR",
                        "currency": "BRL",
                        "duration": "short",
                        "factor": "sovereign_floating",
                        "liquidity_tier": "t0",
                    },
                ],
            },
        },
        {
            "id": "etf_gold11",
            "label": "ETF GOLD11 (Ouro)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="COMMODITIES"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "notes": "Physically-backed gold exposure; listed as stock at B3.",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "commodities",
                        "region": "GLOBAL",
                        "currency": "USD",
                        "sector": "precious_metals",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_hash11",
            "label": "ETF HASH11 (Cripto cesta)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="CRIPTO"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "cryptocurrencies",
                        "region": "GLOBAL",
                        "currency": "USD",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_acwi11",
            "label": "ETF ACWI11 (MSCI ACWI global)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="INTERNACIONAL"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "notes": "Approximate regional split based on MSCI ACWI weights; refresh periodically.",
                "breakdown": [
                    {
                        "weight_pct": 62,
                        "asset_class": "stocks",
                        "region": "US",
                        "currency": "USD",
                        "factor": "broad_market",
                        "liquidity_tier": "t1",
                    },
                    {
                        "weight_pct": 27,
                        "asset_class": "stocks",
                        "region": "ex_US_DM",
                        "currency": "USD",
                        "factor": "broad_market",
                        "liquidity_tier": "t1",
                    },
                    {
                        "weight_pct": 11,
                        "asset_class": "stocks",
                        "region": "EM",
                        "currency": "USD",
                        "factor": "broad_market",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_xina11",
            "label": "ETF XINA11 (China MSCI)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="INTERNACIONAL"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "stocks",
                        "region": "EM_CN",
                        "currency": "USD",
                        "factor": "broad_market",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
        {
            "id": "etf_xfix11",
            "label": "ETF XFIX11 (IFIX - cesta de FIIs)",
            "asset_class": "funds",
            "availability": {"countries": ["BR"]},
            "instrument_attributes": _etf_attrs(underlying_class="RENDA_VARIAVEL"),
            "economic_exposure": {
                "classification_source": "issuer_prospectus",
                "as_of": "2026-04-01",
                "confidence": "high",
                "notes": "Tracks IFIX; economically real estate (FIIs) despite trading as an ETF.",
                "breakdown": [
                    {
                        "weight_pct": 100,
                        "asset_class": "reits",
                        "region": "BR",
                        "currency": "BRL",
                        "liquidity_tier": "t1",
                    },
                ],
            },
        },
    ]


def _attrs_securitized() -> list[dict]:
    return [
        _attr(
            "securitizadora_cnpj",
            "Securitizadora CNPJ",
            "string",
            required=True,
            pattern=BRAZIL_CNPJ_REGEX,
        ),
        _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
        _attr("issue_date", "Issue Date", "string", required=True),
        _attr("maturity_date", "Maturity Date", "string", required=True),
        _attr("remuneration_type", "Remuneration Type", "string", required=True, enum=_REMUNERATION_ENUM),
        _attr("indexer", "Indexer", "string", required=True, enum=BRAZIL_INDEXER_ENUM),
        _attr("spread_pct", "Spread (%)", "number", required=False),
        _attr("spread_bps", "Spread (bps)", "integer", required=False),
        _attr("amortization_schedule", "Amortization Schedule", "string", required=False),
        _attr("interest_schedule", "Interest Schedule", "string", required=False),
        _attr(
            "tax_profile.ir_pf_treatment",
            "Tax Profile: IR PF Treatment",
            "string",
            required=True,
            enum=_IR_PF_TREATMENT_ENUM,
        ),
        _attr(
            "tax_profile.source_rule_ref",
            "Tax Profile: Source Rule Reference",
            "string",
            required=False,
        ),
    ]


class Plugin:
    @hookimpl
    def asset_type_catalog(self, ctx):
        return [
            {
                "id": "fii",
                "label": "FII",
                "asset_class": "real_estate",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("fund_cnpj", "Fund CNPJ", "string", required=True, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("b3_ticker", "B3 Ticker", "string", required=True, pattern=BRAZIL_B3_TICKER_REGEX),
                    _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
                    _attr("fii_type", "FII Type", "string", required=True, enum=_FII_TYPE_ENUM),
                    _attr("segment", "Segment", "string", required=False),
                    _attr("admin_cnpj", "Administrator CNPJ", "string", required=False, pattern=BRAZIL_CNPJ_REGEX),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "tesouro_direto",
                "label": "Tesouro Direto",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
                    _attr("issue_date", "Issue Date", "string", required=True),
                    _attr("maturity_date", "Maturity Date", "string", required=True),
                    _attr(
                        "index",
                        "Tesouro Index",
                        "string",
                        required=True,
                        enum=["IPCA", "SELIC", "PREFIXADO"],
                    ),
                    _attr("expiration_year", "Expiration Year", "integer", required=True),
                    _attr("semestral_payments", "Semestral Payments", "boolean", required=False),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "lci",
                "label": "LCI",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture()
                + [
                    _attr(
                        "min_holding_period_months",
                        "Minimum Holding Period (months)",
                        "integer",
                        required=False,
                    )
                ],
            },
            {
                "id": "lca",
                "label": "LCA",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture()
                + [
                    _attr(
                        "min_holding_period_months",
                        "Minimum Holding Period (months)",
                        "integer",
                        required=False,
                    )
                ],
            },
            {
                "id": "cdb",
                "label": "CDB",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture()
                + [
                    _attr("fgc_eligible", "FGC Eligible", "boolean", required=False),
                    _attr("liquidity_type", "Liquidity Type", "string", required=False,
                          enum=["DIARIA", "NO_VENCIMENTO", "CARENCIA_PARCIAL"]),
                ],
            },
            {
                "id": "lig",
                "label": "LIG",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture(),
            },
            {
                "id": "lf",
                "label": "Letra Financeira",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture(),
            },
            {
                "id": "cri",
                "label": "CRI",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_securitized(),
            },
            {
                "id": "cra",
                "label": "CRA",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_securitized(),
            },
            {
                "id": "debenture",
                "label": "Debenture",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture()
                + [
                    _attr(
                        "tax_benefit_regime",
                        "Tax Benefit Regime",
                        "string",
                        required=False,
                        enum=["NAO_INCENTIVADA"],
                    )
                ],
            },
            {
                "id": "debenture_incentivada",
                "label": "Debenture Incentivada (Lei 12.431)",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture()
                + [
                    _attr(
                        "tax_benefit_regime",
                        "Tax Benefit Regime",
                        "string",
                        required=True,
                        enum=["LEI_12431"],
                    )
                ],
            },
            {
                "id": "debenture_infra",
                "label": "Debenture de Infraestrutura (Lei 14.801)",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": _attrs_credit_letter_or_debenture()
                + [
                    _attr(
                        "tax_benefit_regime",
                        "Tax Benefit Regime",
                        "string",
                        required=True,
                        enum=["LEI_14801"],
                    )
                ],
            },
            {
                "id": "bdr",
                "label": "BDR",
                "asset_class": "stocks",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("b3_ticker", "B3 Ticker", "string", required=True, pattern=BRAZIL_B3_TICKER_REGEX),
                    _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
                    _attr("bdr_level", "BDR Level", "string", required=True, enum=_BDR_LEVEL_ENUM),
                    _attr(
                        "depositary_cnpj",
                        "Depositary CNPJ",
                        "string",
                        required=True,
                        pattern=BRAZIL_CNPJ_REGEX,
                    ),
                    _attr("underlying_identifier", "Underlying Identifier", "string", required=True),
                    _attr(
                        "underlying_country",
                        "Underlying Country (ISO 3166-1 alpha-2)",
                        "string",
                        required=False,
                        pattern=_ISO_3166_ALPHA2_REGEX,
                    ),
                    _attr(
                        "underlying_isin",
                        "Underlying ISIN",
                        "string",
                        required=False,
                        pattern=_ISIN_REGEX,
                    ),
                    _attr("parity_ratio", "Parity Ratio", "number", required=True),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "coe",
                "label": "COE",
                "asset_class": "other",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("issuer_cnpj", "Issuer CNPJ", "string", required=True, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
                    _attr("issue_date", "Issue Date", "string", required=True),
                    _attr("maturity_date", "Maturity Date", "string", required=True),
                    _attr("modalidade", "Modalidade", "string", required=True, enum=_COE_MODALIDADE_ENUM),
                    _attr("underlying_reference", "Underlying Reference", "string", required=True),
                    _attr("payoff_formula", "Payoff Formula", "string", required=True),
                    _attr("indexer", "Indexer", "string", required=False, enum=BRAZIL_INDEXER_ENUM),
                    _attr("remuneration_type", "Remuneration Type", "string", required=False, enum=_REMUNERATION_ENUM),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "fidc_cota",
                "label": "FIDC Cota",
                "asset_class": "funds",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("fund_cnpj", "Fund CNPJ", "string", required=True, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("class_id", "Class ID", "string", required=True),
                    _attr("subclass_type", "Subclass Type", "string", required=True, enum=_FIDC_SUBCLASS_ENUM),
                    _attr("target_investor", "Target Investor", "string", required=False, enum=_FIDC_TARGET_INVESTOR_ENUM),
                    _attr("open_closed", "Open or Closed", "string", required=True, enum=_OPEN_CLOSED_ENUM),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "fiagro_cota",
                "label": "FIAGRO Cota",
                "asset_class": "funds",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("fund_cnpj", "Fund CNPJ", "string", required=True, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("class_id", "Class ID", "string", required=True),
                    _attr("target_chain", "Target Chain", "string", required=True, enum=_TARGET_CHAIN_ENUM),
                    _attr("fiagro_strategy", "FIAGRO Strategy", "string", required=True, enum=_FIAGRO_STRATEGY_ENUM),
                    _attr("open_closed", "Open or Closed", "string", required=False, enum=_OPEN_CLOSED_ENUM),
                    _attr("b3_ticker", "B3 Ticker", "string", required=False, pattern=BRAZIL_B3_TICKER_REGEX),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "acao",
                "label": "Ação",
                "asset_class": "stocks",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("b3_ticker", "B3 Ticker", "string", required=True, pattern=BRAZIL_B3_TICKER_REGEX),
                    _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
                    _attr("issuer_cnpj", "Issuer CNPJ", "string", required=False, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("share_class", "Share Class", "string", required=True, enum=_ACAO_SHARE_CLASS_ENUM),
                    _attr("segment", "B3 Listing Segment", "string", required=False),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "etf",
                "label": "ETF",
                "asset_class": "funds",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("b3_ticker", "B3 Ticker", "string", required=True, pattern=BRAZIL_B3_TICKER_REGEX),
                    _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
                    _attr("fund_cnpj", "Fund CNPJ", "string", required=False, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("underlying_class", "Underlying Asset Class", "string", required=True, enum=_ETF_UNDERLYING_CLASS_ENUM),
                    _attr("benchmark_index", "Benchmark Index", "string", required=False),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "fundo_investimento",
                "label": "Fundo de Investimento",
                "asset_class": "funds",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("fund_cnpj", "Fund CNPJ", "string", required=True, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("isin", "ISIN", "string", required=False, pattern=BRAZIL_ISIN_REGEX),
                    _attr("category", "Anbima Category", "string", required=True, enum=_FUND_CATEGORY_ENUM),
                    _attr("admin_cnpj", "Administrator CNPJ", "string", required=False, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("manager_cnpj", "Manager CNPJ", "string", required=False, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("open_closed", "Open or Closed", "string", required=False, enum=_OPEN_CLOSED_ENUM),
                    _attr("benchmark", "Benchmark", "string", required=False),
                    _attr("come_cotas_applicable", "Come-Cotas Applicable", "boolean", required=False),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            {
                "id": "previdencia_privada",
                "label": "Previdência Privada",
                "asset_class": "funds",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": [
                    _attr("plan_type", "Plan Type", "string", required=True, enum=_PREV_PLAN_TYPE_ENUM),
                    _attr("provider_cnpj", "Provider CNPJ", "string", required=True, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("fund_cnpj", "Underlying Fund CNPJ", "string", required=False, pattern=BRAZIL_CNPJ_REGEX),
                    _attr("susep_process", "SUSEP Process Number", "string", required=False),
                    _attr("tax_regime", "Tax Regime", "string", required=True, enum=_PREV_REGIME_ENUM),
                    _attr(
                        "tax_profile.ir_pf_treatment",
                        "Tax Profile: IR PF Treatment",
                        "string",
                        required=True,
                        enum=_IR_PF_TREATMENT_ENUM,
                    ),
                ],
            },
            *_known_br_etfs(),
        ]
