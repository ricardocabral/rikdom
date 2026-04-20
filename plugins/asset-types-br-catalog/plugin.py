from __future__ import annotations

from rikdom.plugin_engine.contracts import (
    BRAZIL_B3_TICKER_REGEX,
    BRAZIL_CNPJ_REGEX,
    BRAZIL_INDEXER_ENUM,
    BRAZIL_ISIN_REGEX,
)
from rikdom.plugin_engine.hookspecs import hookimpl


_REMUNERATION_ENUM = ["PREFIXADO", "POS", "HIBRIDO"]
_IR_PF_TREATMENT_ENUM = ["ISENTO", "REGRESSIVO", "ALIQUOTA_FIXA", "OUTRO"]
_BDR_LEVEL_ENUM = ["N1_NAO_PATROCINADO", "N1_PATROCINADO", "N2_PATROCINADO", "N3_PATROCINADO"]
_COE_MODALIDADE_ENUM = ["VALOR_NOMINAL_PROTEGIDO", "VALOR_NOMINAL_EM_RISCO"]
_FIDC_SUBCLASS_ENUM = ["SENIOR", "SUBORDINADA_MEZANINO", "SUBORDINADA_JUNIOR"]
_OPEN_CLOSED_ENUM = ["ABERTO", "FECHADO"]
_TARGET_CHAIN_ENUM = ["CADEIA_AGRO"]
_FIAGRO_STRATEGY_ENUM = ["TERRA", "FIDC_LIKE", "FIP_LIKE", "MULTI"]


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
        item["enum"] = enum
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
        credit_attrs = _attrs_credit_letter_or_debenture()
        securitized_attrs = _attrs_securitized()
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
                    _attr("segment", "Segment", "string", required=False),
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
                "instrument_attributes": credit_attrs,
            },
            {
                "id": "lca",
                "label": "LCA",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": credit_attrs,
            },
            {
                "id": "cri",
                "label": "CRI",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": securitized_attrs,
            },
            {
                "id": "cra",
                "label": "CRA",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": securitized_attrs,
            },
            {
                "id": "debenture_incentivada",
                "label": "Debenture Incentivada",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": credit_attrs
                + [
                    _attr(
                        "tax_benefit_regime",
                        "Tax Benefit Regime",
                        "string",
                        required=True,
                        enum=["LEI_12431", "LEI_14801"],
                    )
                ],
            },
            {
                "id": "debenture_infra",
                "label": "Debenture de Infraestrutura",
                "asset_class": "debt",
                "availability": {"countries": ["BR"]},
                "instrument_attributes": credit_attrs
                + [
                    _attr(
                        "tax_benefit_regime",
                        "Tax Benefit Regime",
                        "string",
                        required=True,
                        enum=["LEI_12431", "LEI_14801"],
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
        ]
