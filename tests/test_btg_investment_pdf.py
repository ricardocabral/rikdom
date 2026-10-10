import importlib.util
from pathlib import Path
import unittest


def load_parser():
    path = Path(__file__).parents[1] / "plugins/btg-investment-pdf/parser.py"
    spec = importlib.util.spec_from_file_location("btg_investment_pdf_parser", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEADER = """Conta investimento 000123456
Período de 01/10/26 a 09/10/26
Emitido em 09/10/26 21:09
Sumário - Distribuição em 09/10/26
Renda Variável*  0,00  0,00  50,00  50,00
Renda Fixa*  0,00  0,00  100,00  99,00
Fundos de Investimento*  0,00  0,00  20,00  18,00
Valores em Trânsito  0,00  0,00  5,00  5,00
Conta Corrente  0,00  0,00  10,00  10,00
Total  0,00  0,00  185,00  182,00
"""
BODY = """Fundo de Investimento - Posição - Portfólio de fundos
FUNDO EXEMPLO - Classe CNPJ: 12.345.678/0001-95*
08/10/26  0,00  10,00000000  2,00000000  20,00  2,00  -  18,00  0,00
Renda fixa - Posição - CDB
Emissor :
BANCO EXEMPLO
Ativo :  Emissão :  Vencimento :
CDB-CDBEXAMPLE  01/01/26  01/01/28  Sim
Taxa Média Ponderada  Quantidade :  Preço R$ :  Saldo Bruto R$ :  IR R$ :  IOF R$ :
:  100,0  1,000000  100,00  1,00  -
102,00% do CDI
Saldo Líquido R$ :
99,00
Renda variável - Posição - Fundos Listados
ABCD12*  DIREITO EXEMPLO  FII  100  0,50  -  50,00
Conta corrente - Posição
09/10/26  10,00
Valores em trânsito - Renda Variável
14/10/26  RENDIMENTO - EXEMPLO  5,00
Total  5,00
"""


class BtgInvestmentPdfTests(unittest.TestCase):
    def test_compact_fixed_income_table_and_old_fund_heading(self):
        compact = (
            "Renda fixa - Posição - CDB\n"
            "Emissor              Ativo              Emissão     Vencimento   Quantidade  Preço R$    Saldo Bruto R$  IR R$  IOF R$  Saldo Líquido R$\n\n"
            "BANCO EXEMPLO        CDB-CDBEXAMPLE      01/01/26    01/01/28     100,0       1,000000    100,00          1,00   -       99,00\n"
        )
        start = BODY.index("Renda fixa - Posição - CDB")
        end = BODY.index("Renda variável - Posição - Fundos Listados")
        body = (BODY[:start] + compact + BODY[end:]).replace(
            "Classe CNPJ:", "Fundo CNPJ:"
        )
        result = load_parser().parse_statement(HEADER + body, "synthetic.txt")
        cdb = next(h for h in result["holdings"] if h["asset_type_id"] == "cdb")
        self.assertEqual(cdb["quantity"], 100)
        self.assertEqual(cdb["valuation"]["net_value"]["amount"], 99)

    def test_unknown_settlement_date_with_split_value_is_preserved(self):
        body = BODY.replace(
            "14/10/26  RENDIMENTO - EXEMPLO  5,00",
            "N/D  RENDIMENTO - EXEMPLO\n SAC: 0800-000-0000 / Ouvidoria: 0800-000-0001  5,00",
        )
        result = load_parser().parse_statement(HEADER + body, "synthetic.txt")
        receivable = next(
            h
            for h in result["holdings"]
            if h["metadata"]["statement_category"] == "Valores em Trânsito"
        )
        self.assertIsNone(receivable["metadata"]["receivables"][0]["settlement_date"])

    def test_footer_split_listed_row_is_reconstructed(self):
        body = BODY.replace(
            "ABCD12*  DIREITO EXEMPLO  FII  100  0,50  -  50,00",
            "ABCD12*  DIREITO EXEMPLO  FII  SAC: 0800-000-0000\n  100  0,50  -  50,00",
        )
        result = load_parser().parse_statement(HEADER + body, "synthetic.txt")
        self.assertEqual(result["metadata"]["ending_account_value"], 185)

    def test_full_statement_reconciles_and_preserves_rights_and_dates(self):
        result = load_parser().parse_statement(HEADER + BODY, "synthetic.txt")
        self.assertEqual(
            sum(h["market_value"]["amount"] for h in result["holdings"]), 185
        )
        fund = next(h for h in result["holdings"] if "cnpj" in h["identifiers"])
        self.assertTrue(fund["as_of"].startswith("2026-10-08"))
        self.assertEqual(fund["valuation"]["net_value"]["amount"], 18)
        right = next(
            h for h in result["holdings"] if h["identifiers"].get("ticker") == "ABCD12"
        )
        self.assertEqual(right["quantity"], 100)
        cdb = next(h for h in result["holdings"] if h["asset_type_id"] == "cdb")
        self.assertEqual(
            cdb["fixed_income_profile"]["coupon"]["indexer_multiplier_pct"], 102
        )
        self.assertEqual(cdb["identifiers"]["provider_account_id"], "123456")
        self.assertEqual(len(result["statement_observations"][0]["sections"]), 5)

    def test_unparsed_position_fails_reconciliation(self):
        with self.assertRaisesRegex(ValueError, "reconcil"):
            load_parser().parse_statement(
                HEADER + BODY.replace("100,00  1,00", "101,00  1,00"), "synthetic.txt"
            )

    def test_deterministic_identity_not_source_path(self):
        parser = load_parser()
        a = parser.parse_statement(HEADER + BODY, "a.txt")
        b = parser.parse_statement(HEADER + BODY, "b.txt")
        self.assertEqual(
            [h["id"] for h in a["holdings"]], [h["id"] for h in b["holdings"]]
        )

    def test_detail_lots_are_observations_and_keep_two_acquisitions(self):
        detail = """Renda fixa - Detalhamento - CDB | BANCO EXEMPLO
Ativo :  Emissão :  Vencimento :  Aquisição :
CDB-CDBEXAMPLE  01/01/26  01/01/28  01/01/26
Data inicial  Taxa Compra :  Quantidade :  Preço Compra R$ :  Valor Compra R$ :  Preço R$ :
de liquidez :  102,00% do CDI  40,0  1,0000  40,00  1,0000
Saldo Bruto R$ :  IR R$ :  IOF R$ :  Saldo Líquido R$ :
40,00  0,40  -  39,60
\fAtivo :  Emissão :  Vencimento :  Aquisição :
CDB-CDBEXAMPLE  01/01/26  01/01/28  02/01/26
Data inicial  Taxa Compra :  Quantidade :  Preço Compra R$ :  Valor Compra R$ :  Preço R$ :
de liquidez :  CDI  60,0  1,0000  60,00  1,0000
Saldo Bruto R$ :  IR R$ :  IOF R$ :  Saldo Líquido R$ :
60,00  0,60  -  59,40
"""
        result = load_parser().parse_statement(HEADER + BODY + detail, "synthetic.txt")
        h = next(h for h in result["holdings"] if h["asset_type_id"] == "cdb")
        observations = h["acquisition_observations"]
        self.assertEqual([o["quantity"] for o in observations], [40, 60])
        self.assertTrue(observations[1]["source_ref"].endswith("#page=2"))
        self.assertNotIn("tax_lots", h)

    def test_lending_valuation_is_accrued_income_not_duplicate_shares(self):
        header = HEADER.replace("50,00  50,00", "51,00  51,00").replace(
            "185,00  182,00", "186,00  183,00"
        )
        loan = """Renda variável - Posição - Ações | Aluguel
ABCD12  100  Doador  0,50  50,00  01/10/26  14/10/26  0,10  -  -  1,00
Total em Aluguel
de Ações R$  50,00  1,00
"""
        p = load_parser().parse_statement(header + BODY + loan, "synthetic.txt")
        self.assertEqual(sum(h["market_value"]["amount"] for h in p["holdings"]), 186)
        self.assertEqual(
            len(
                [h for h in p["holdings"] if h["identifiers"].get("ticker") == "ABCD12"]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
