import importlib.util
import json
import sys
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from xml.etree.ElementTree import fromstring

from rikdom.plugin_engine.pipeline import run_import_pipeline


def load_importer(name):
    spec = importlib.util.spec_from_file_location("identity_" + name.replace("-", "_"), Path("plugins") / name / "importer.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SourceIdentityTests(unittest.TestCase):
    def test_irpf_owns_brazilian_ticker_and_fund_identity(self):
        importer = load_importer("irpf-xml")
        rows = [("03", "01", "BBDC4", "", "br:acao:bbdc4"),
                ("07", "03", "DEMO11", "", "br:fii:demo11"),
                ("04", "04", "AAPL34", "", "br:bdr:aapl34"),
                ("07", "01", "", "30.934.757/0001-13", "br:fund:30934757000113")]
        for group, code, ticker, cnpj, expected in rows:
            item = fromstring(f'<bem grupo="{group}" codigo="{code}" codigoNegociacao="{ticker}" niEmpresa="{cnpj}" pais="105" valorExercicioAtual="1,00"/>')
            holding = importer._build_holding(item, exercicio=2026)
            self.assertEqual(holding["metadata"]["canonical_key"], expected)

    def test_irpf_does_not_guess_foreign_country(self):
        importer = load_importer("irpf-xml")
        item = fromstring('<bem grupo="03" codigo="01" codigoNegociacao="VTI" pais="249" valorExercicioAtual="1,00"/>')
        holding = importer._build_holding(item, exercicio=2026)
        self.assertNotIn("canonical_key", holding["metadata"])

    def test_us_broker_produces_ticker_and_cash_keys(self):
        payload = run_import_pipeline(plugin_name="charles-schwab", plugins_dir="plugins", input_path="plugins/charles-schwab/fixtures/taxable-mixed/input.csv")
        for holding in payload["holdings"]:
            key = holding["metadata"]["canonical_key"]
            if holding["asset_type_id"] == "cash_equivalent":
                self.assertEqual(key, "cash:usd")
            else:
                self.assertEqual(key, f'us:{holding["asset_type_id"]}:{holding["identifiers"]["ticker"].lower()}')

    def test_generic_json_does_not_guess_geography(self):
        payload = run_import_pipeline(plugin_name="wealthfolio_export_json", plugins_dir="plugins", input_path="tests/fixtures/wealthfolio_export_sample.json")
        self.assertNotIn("canonical_key", payload["holdings"][0].get("metadata", {}))

    def test_json_sources_preserve_explicit_key_and_unknown_metadata(self):
        for name in ("ghostfolio_export_json", "wealthfolio_export_json"):
            importer = load_importer(name)
            metadata = {"canonical_key": "opaque:source-key", "custom": {"nested": 42}}
            item = {"id": "h", "symbol": "VTI", "marketValue": 100, "currency": "USD", "metadata": metadata}
            if name == "ghostfolio_export_json":
                holding = importer._normalize_holding(item)
            else:
                holding = importer._normalize_holding(item, {})
            self.assertEqual(holding.get("metadata"), metadata)

    def test_csv_generic_preserves_explicit_key_without_deriving(self):
        importer = load_importer("csv-generic")
        row = {"id": "h", "asset_type_id": "stock", "label": "Asset", "amount": "100", "currency": "USD", "ticker": "VTI", "canonical_key": "opaque:provided", "fx_rate_to_base": "1"}
        holding = importer._to_holding(row)
        self.assertEqual(holding["metadata"], {"canonical_key": "opaque:provided", "fx_rate_to_base": 1.0})

    def test_ibkr_skipped_non_cash_corporate_action_is_reported(self):
        xml = """<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">
        <CashTransactions><CashTransaction transactionID="cash-1" type="Dividends" amount="1" currency="USD" dateTime="20260421;100000"/></CashTransactions>
        <CorporateActions><CorporateAction transactionID="ca-unknown" symbol="XYZ" type="SPIN" description="Non-cash spin-off" quantity="10" proceeds="0" dateTime="20260421;110000"/></CorporateActions>
        </FlexStatement></FlexStatements></FlexQueryResponse>"""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "statement.xml"
            path.write_text(xml)
            payload = run_import_pipeline(plugin_name="ibkr_flex_xml", plugins_dir="plugins", input_path=str(path))
        diagnostic = payload.get("metadata", {}).get("rikdom_import_diagnostics", {})
        self.assertEqual(diagnostic.get("history_coverage", [{}])[0].get("status"), "partial")
        unsupported = diagnostic.get("unsupported_events", [])
        self.assertTrue(any(event["source_event"] == "SPIN" and "ca-unknown" in event["source_ref"] and event["affects_quantity"] for event in unsupported))

    def test_positions_only_source_does_not_claim_activity_coverage(self):
        payload = run_import_pipeline(plugin_name="irpf-xml", plugins_dir="plugins", input_path="plugins/irpf-xml/fixtures/sample/input.xml")
        diagnostics = payload.get("metadata", {}).get("rikdom_import_diagnostics", {})
        coverage = diagnostics.get("history_coverage", [{}])[0]
        self.assertEqual(coverage.get("status"), "unknown")
        self.assertEqual(coverage.get("event_types"), [])
        self.assertNotIn("from", coverage)
        self.assertNotIn("through", coverage)

    def test_ibkr_unsupported_only_statement_retains_diagnostic_evidence(self):
        xml = '<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1"><CorporateActions><CorporateAction transactionID="ca-only" type="SPIN" quantity="10" proceeds="0" dateTime="20260421;110000"/></CorporateActions></FlexStatement></FlexStatements></FlexQueryResponse>'
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "statement.xml"
            path.write_text(xml)
            payload = run_import_pipeline(plugin_name="ibkr_flex_xml", plugins_dir="plugins", input_path=str(path))
        self.assertEqual(payload["activities"], [])
        self.assertEqual(payload["metadata"]["rikdom_import_diagnostics"]["unsupported_events"][0]["source_event"], "SPIN")

    def test_vanguard_reports_unhandled_ofx_transaction_type(self):
        raw = Path("plugins/vanguard/fixtures/ofx-brokerage/input.ofx").read_text()
        raw = raw.replace("</INVTRANLIST>", '<TRANSFER><INVTRAN><FITID>unknown-transfer</FITID><DTTRADE>20260330</DTTRADE></INVTRAN><UNITS>3</UNITS></TRANSFER></INVTRANLIST>')
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "statement.ofx"
            path.write_text(raw)
            payload = run_import_pipeline(plugin_name="vanguard", plugins_dir="plugins", input_path=str(path))
        unsupported = payload["metadata"]["rikdom_import_diagnostics"]["unsupported_events"]
        self.assertTrue(any(event["source_event"] == "TRANSFER" and "unknown-transfer" in event["source_ref"] for event in unsupported))

    def test_normalized_input_preserves_explicit_diagnostics_and_metadata(self):
        diagnostics = {"version": 1, "history_coverage": [{"scope": "account-a", "status": "complete", "event_types": ["buy"], "reasons": ["source declaration"], "from": "2026-01-01", "through": "2026-01-31"}], "unsupported_events": []}
        raw = {"provider": "custom", "generated_at": "2026-02-01T00:00:00Z", "holdings": [], "metadata": {"custom": {"keep": True}, "rikdom_import_diagnostics": diagnostics}}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "statement.json"
            path.write_text(json.dumps(raw))
            payload = run_import_pipeline(plugin_name="normalized-statement-json", plugins_dir="plugins", input_path=str(path))
        self.assertEqual(payload, raw)

    def test_b3_sheet_declares_ticker_kind_independent_of_generic_asset_type(self):
        importer = load_importer("b3-consolidado-mensal")
        for sheet, ticker, key in (("Posição - Ações", "BBDC4", "br:acao:bbdc4"), ("Posição - ETF", "BOVA11", "br:etf:bova11"), ("Posição - BDR", "AAPL34", "br:bdr:aapl34")):
            spec = next(s for s in importer.SHEET_SPECS if s.name == sheet)
            holding = importer._to_holding(spec, {"Produto": "Security", "Código de Negociação": ticker, "Valor Atualizado": "100,00", "Quantidade": "1"})
            self.assertEqual(holding.get("metadata", {}).get("canonical_key"), key)

    def test_cash_like_securities_and_receivables_are_not_identified_as_cash(self):
        importer = load_importer("charles-schwab")
        holding = importer._parse_position({"account_number": "a", "symbol": "SWVXX", "description": "Money market fund", "quantity": "1", "market_value": "1", "security_type": "Money Market", "currency": "USD"})
        importer._assign_canonical_key(holding)
        self.assertNotIn("canonical_key", holding.get("metadata", {}))
        payload = run_import_pipeline(plugin_name="btg-investment-pdf", plugins_dir="plugins", input_path="plugins/btg-investment-pdf/fixtures/default/input.txt")
        for position in payload["holdings"]:
            if position["metadata"]["statement_category"] == "Valores em Trânsito":
                self.assertNotIn("canonical_key", position["metadata"])

    def test_irpf_tax_reporting_currency_does_not_identify_foreign_cash(self):
        importer = load_importer("irpf-xml")
        item = fromstring('<bem grupo="06" codigo="01" pais="249" valorExercicioAtual="100,00"/>')
        holding = importer._build_holding(item, exercicio=2026)
        self.assertNotIn("canonical_key", holding.get("metadata", {}))
