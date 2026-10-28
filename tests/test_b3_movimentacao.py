from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rikdom.cli import main
from rikdom.import_preflight import build_preflight_report
from rikdom.plugin_engine.pipeline import run_import_pipeline
from rikdom.plugins import merge_activities, stamp_provenance
from rikdom.storage import load_json, save_json
from test_b3_consolidado_mensal_importer import _write_workbook


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "plugins/b3-consolidado-mensal/fixtures/movimentacao_minimal/input.xlsx"
HEADERS = ["Entrada/Saída", "Data", "Movimentação", "Produto", "Instituição", "Quantidade", "Preço unitário", "Valor da Operação"]


def parse(path: Path) -> dict:
    return run_import_pipeline("b3-consolidado-mensal", str(ROOT / "plugins"), str(path))


class B3MovimentacaoTests(unittest.TestCase):
    def test_synthetic_fixture_maps_observed_movements_without_inventing_context(self):
        payload = parse(FIXTURE)
        self.assertEqual(payload["holdings"], [])
        self.assertEqual([a["event_type"] for a in payload["activities"]], ["buy", "buy", "sell", "dividend", "dividend", "income", "transfer_in", "transfer_out"])
        self.assertEqual(payload["activities"][0]["quantity"], 7)
        self.assertEqual(payload["activities"][0]["money"], {"amount": 93.59, "currency": "BRL"})
        self.assertEqual(payload["activities"][0]["effective_at"], "2001-02-03T02:00:00Z")
        self.assertNotIn("trade_at", payload["activities"][0])
        self.assertNotIn("settled_at", payload["activities"][0])
        self.assertNotIn("account_id", payload["activities"][0])
        self.assertNotIn("asset_type_id", payload["activities"][0])
        self.assertNotIn("quantity", payload["activities"][3])
        self.assertNotIn("money", payload["activities"][6])
        diagnostic = payload["metadata"]["rikdom_import_diagnostics"]
        self.assertEqual(len(diagnostic["unsupported_events"]), 2)
        self.assertTrue(all(c["status"] == "partial" for c in diagnostic["history_coverage"]))
        self.assertTrue(all("from" not in c for c in diagnostic["history_coverage"]))
        self.assertEqual(len({a["id"] for a in payload["activities"]}), 8)

    def test_income_preserves_unknown_reported_gross_net_basis(self):
        income = [a for a in parse(FIXTURE)["activities"] if a["event_type"] in {"dividend", "interest", "income"}]
        self.assertTrue(income)
        for activity in income:
            self.assertEqual(activity["metadata"]["rikdom_income"], {"version": 1, "amount_basis": "unknown"})
            self.assertEqual(activity["metadata"]["amount_basis"], "reported_gross_net_unknown")

    def test_repeated_file_keeps_identical_executions_distinct_and_noops(self):
        payload = parse(FIXTURE)
        p = {"holdings": [], "activities": []}
        for run in ("one", "two"):
            incoming = copy.deepcopy(payload)
            stamp_provenance(incoming, source_system=incoming["provider"], import_run_id=run, ingested_at="2001-02-14T12:00:00Z")
            self.assertTrue(build_preflight_report(p, incoming)["ok"])
            _, counts = merge_activities(p, incoming)
            self.assertEqual(counts.inserted, 8 if run == "one" else 0)
        self.assertEqual(len(p["activities"]), 8)
        self.assertNotEqual(p["activities"][0]["idempotency_key"], p["activities"][1]["idempotency_key"])

    def test_reorder_preserves_fingerprint_and_anonymous_occurrence_identity(self):
        rows = [
            ["Entrada", "03/02/2001", "Transferência - Liquidação", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 7, 13.37, 93.59],
            ["Saída", "04/02/2001", "Transferência - Liquidação", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 4, 14.15, 56.6],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic.xlsx"
            _write_workbook(path, [("Movimentação", HEADERS, rows)])
            first = parse(path)
            _write_workbook(path, [("Movimentação", HEADERS, list(reversed(rows)))])
            second = parse(path)
        self.assertEqual(first["metadata"]["rikdom_import_diagnostics"]["document_fingerprint"], second["metadata"]["rikdom_import_diagnostics"]["document_fingerprint"])
        self.assertEqual({a["id"] for a in first["activities"]}, {a["id"] for a in second["activities"]})
        self.assertEqual({json.dumps(a, sort_keys=True) for a in first["activities"]}, {json.dumps(a, sort_keys=True) for a in second["activities"]})

    def test_overlapping_anonymous_exports_block_before_duplicate_import(self):
        original = parse(FIXTURE)
        p = {"holdings": [], "activities": copy.deepcopy(original["activities"])}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic-overlap.xlsx"
            _write_workbook(path, [("Movimentação", HEADERS, [["Entrada", "03/02/2001", "Transferência - Liquidação", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 7, 13.37, 93.59]])])
            overlap = parse(path)
        report = build_preflight_report(p, overlap)
        self.assertFalse(report["ok"])
        self.assertIn("AMBIGUOUS_IMPORT_IDENTITY", [i["code"] for i in report["issues"]])

    def test_malformed_columns_and_dates_fail_without_silently_skipping_rows(self):
        row = ["Entrada", "not-a-date", "Dividendo", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 3, 1.11, 3.33]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic-invalid.xlsx"
            _write_workbook(path, [("Movimentação", HEADERS, [row])])
            with self.assertRaises(ValueError):
                parse(path)
            _write_workbook(path, [("Movimentação", HEADERS[:-1], [row[:-1]])])
            with self.assertRaises(ValueError):
                parse(path)

    def test_diagnostics_preserve_the_physical_excel_row_after_gaps(self):
        unsupported = ["Entrada", "11/02/2001", "Evento Sintético Não Suportado", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 1, "-", "-"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic-rows.xlsx"
            _write_workbook(path, [("Movimentação", HEADERS, [[None] * 8, unsupported])])
            payload = parse(path)
        self.assertEqual(payload["metadata"]["rikdom_import_diagnostics"]["unsupported_events"][0]["source_ref"], "Movimentação:row:3")

    def test_transfer_only_institution_does_not_claim_other_event_categories(self):
        payload = parse(FIXTURE)
        scope = payload["activities"][6]["metadata"]["rikdom_source_identity"]["scope"]
        coverage = next(c for c in payload["metadata"]["rikdom_import_diagnostics"]["history_coverage"] if c["scope"] == scope)
        self.assertEqual(coverage["event_types"], ["transfer_in", "transfer_out"])

    def test_cli_quantity_comparison_requires_reviewed_evidence_and_respects_boundaries(self):
        rows = [
            ["Entrada", "03/02/2001", "Transferência - Liquidação", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 7, 13.37, 93.59],
            ["Entrada", "03/02/2001", "Transferência - Liquidação", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 7, 13.37, 93.59],
            ["Saída", "04/02/2001", "Transferência - Liquidação", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 4, 14.15, 56.6],
            ["Entrada", "05/02/2001", "Transferência - Liquidação", "ZZZA3 - EMPRESA SINTETICA A", "CORRETORA FICTICIA ALFA", 99, 1, 99],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, out = root / "data", root / "out"
            path, workbook = data / "portfolio.json", root / "synthetic.xlsx"
            _write_workbook(workbook, [("Movimentação", HEADERS, rows)])
            p = load_json(ROOT / "tests/fixtures/portfolio.json")
            holding = {"id": "synthetic-position", "label": "Synthetic equity", "account_id": "synthetic-account", "asset_type_id": "stock", "quantity": 10, "as_of": "2001-02-04T23:59:59-02:00", "identifiers": {"ticker": "ZZZA3"}, "market_value": {"amount": 141.5, "currency": "BRL"}}
            p.update(holdings=[holding], activities=[], extensions={})
            save_json(path, p)

            def run(plugin, source, *flags):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(["import-statement", "--plugin", plugin, "--input", str(source), "--data-dir", str(data), "--out-root", str(out), "--plugins-dir", str(ROOT / "plugins"), "--reconcile", *flags])
                self.assertEqual(code, 0, stderr.getvalue())
                return json.loads(stdout.getvalue())

            result = run("b3-consolidado-mensal", workbook, "--write")
            self.assertEqual(result["reconciliation"]["quantity_summary"]["not_computable"], 1)
            run("b3-consolidado-mensal", workbook, "--write")
            self.assertEqual(len(load_json(path)["activities"]), 4)

            # These are explicit synthetic user declarations, never inferred by B3.
            activities = copy.deepcopy(load_json(path)["activities"])
            for activity in activities:
                activity.update(account_id=holding["account_id"], holding_id=holding["id"], trade_at=activity["effective_at"], settled_at="2001-02-06T12:00:00Z")
            scope = activities[0]["metadata"]["rikdom_source_identity"]["scope"]
            coverage = {"scope": scope, "account_id": holding["account_id"], "holding_id": holding["id"], "status": "complete", "event_types": ["buy", "sell"], "from": "2001-02-03", "through": "2001-02-04", "timezone": "America/Sao_Paulo", "history_origin": "inception", "opening_quantity": 0, "position_basis": "trade", "evidence": {"kind": "user_declaration", "source_ref": "synthetic-reviewed-evidence"}}
            evidence = {"provider": "b3-consolidado-mensal", "generated_at": "2001-02-07T12:00:00Z", "holdings": [holding], "activities": activities, "metadata": {"rikdom_import_diagnostics": {"version": 1, "document_fingerprint": "synthetic-reviewed-evidence", "history_coverage": [coverage], "unsupported_events": []}}}
            statement = root / "reviewed-evidence.json"
            cases = [
                ("trade basis includes local end day and excludes later trade", {}, 10, "matched"),
                ("quantity mismatch", {}, 11, "mismatched"),
                ("coverage ends before position", {"through": "2001-02-03"}, 10, "not_computable"),
                ("nonzero opening", {"opening_quantity": 1}, 10, "not_computable"),
                ("partial history", {"status": "partial"}, 10, "not_computable"),
                ("settled basis is unsupported", {"position_basis": "settled"}, 10, "not_computable"),
            ]
            for name, changes, quantity, expected in cases:
                with self.subTest(name=name):
                    candidate = copy.deepcopy(evidence)
                    candidate["holdings"][0]["quantity"] = quantity
                    candidate["metadata"]["rikdom_import_diagnostics"]["history_coverage"][0].update(changes)
                    save_json(statement, candidate)
                    before = path.read_bytes(), (data / "import_log.jsonl").read_bytes()
                    result = run("normalized-statement-json", statement, "--dry-run")
                    self.assertEqual(result["reconciliation"]["quantity_summary"][expected], 1)
                    self.assertEqual((path.read_bytes(), (data / "import_log.jsonl").read_bytes()), before)
            save_json(statement, evidence)
            result = run("normalized-statement-json", statement, "--write")
            self.assertEqual(result["reconciliation"]["quantity_summary"]["matched"], 1)
            self.assertEqual(len(load_json(path)["activities"]), 4)


if __name__ == "__main__":
    unittest.main()
