from __future__ import annotations

import io
import json
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rikdom.aggregate import aggregate_portfolio
from rikdom.cli import main
from rikdom.validate import validate_portfolio


class AggregateTrustCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.portfolio_path = self.root / "portfolio.json"
        self.fx_path = self.root / "fx.jsonl"
        self.fx_path.write_text("")
        self.portfolio = json.loads(Path("tests/fixtures/portfolio.json").read_text())
        self.portfolio["settings"]["base_currency"] = "USD"
        self.portfolio["activities"] = []
        self.portfolio["holdings"] = [
            {
                "id": holding_id,
                "asset_type_id": "stock",
                "label": holding_id,
                "market_value": {"amount": amount, "currency": currency},
                "as_of": "2026-01-01T00:00:00Z",
            }
            for holding_id, amount, currency in (
                ("domestic", 100, "USD"),
                ("foreign", 900, "EUR"),
            )
        ]
        self.assertEqual(validate_portfolio(self.portfolio), [])
        self.portfolio_path.write_text(json.dumps(self.portfolio))

    def aggregate(self, *extra: str) -> tuple[int, dict, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            redirect_stdout(stdout), redirect_stderr(stderr),
            patch("rikdom.cli._now_iso", return_value="2026-11-09T12:00:00Z"),
        ):
            try:
                code = main([
                    "aggregate", "--data-dir", str(self.root),
                    "--out-root", str(self.root / "out"),
                    "--portfolio", str(self.portfolio_path),
                    "--fx-history", str(self.fx_path), *extra,
                ])
            except SystemExit as exc:
                code = exc.code
        output = stdout.getvalue()
        return code, json.loads(output) if output else {}, stderr.getvalue()

    def test_excluded_foreign_holding_retains_native_evidence(self) -> None:
        code, output, stderr = self.aggregate("--include-trust")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(output["portfolio_value_base"], 100)
        holdings = {row["holding_id"]: row for row in output["trust"]["holdings"]}
        self.assertEqual(set(holdings), {"domestic", "foreign"})
        foreign = holdings["foreign"]
        self.assertEqual(foreign["asset_type_id"], "stock")
        self.assertEqual(foreign["source_amount"], 900)
        self.assertEqual(foreign["source_currency"], "EUR")
        self.assertEqual(foreign["base_currency"], "USD")
        self.assertEqual(foreign["excluded_reason"], "fx_missing")
        self.assertIn("RECON_FX_MISSING", foreign["findings"])
        self.assertNotIn("base_amount", foreign)
        self.assertNotIn("fx_rate", foreign)
        finding = next(
            row for row in output["trust"]["findings"]
            if row["code"] == "RECON_FX_MISSING"
        )
        self.assertEqual(finding["refs"], {"holding_id": "foreign"})
        self.assertEqual(finding["scope"], "holding")
        self.assertEqual(output["trust"]["fx_context"]["rates_to_base"], {})

    def test_explicit_cached_fx_includes_foreign_holding_and_retains_selection(self) -> None:
        self.fx_path.write_text(
            '{"as_of_date":"2026-01-01","base_currency":"USD",'
            '"quote_currency":"EUR","rate_to_base":1.1,"source":"synthetic-cache"}\n'
            '{"as_of_date":"2099-01-01","base_currency":"USD",'
            '"quote_currency":"EUR","rate_to_base":500,"source":"future"}\n'
        )
        code, output, stderr = self.aggregate("--include-trust")

        self.assertEqual((code, stderr), (0, ""))
        self.assertAlmostEqual(output["portfolio_value_base"], 1090)
        foreign = output["trust"]["holdings"][1]
        self.assertEqual(foreign["holding_id"], "foreign")
        self.assertEqual(foreign["source_amount"], 900)
        self.assertEqual(foreign["source_currency"], "EUR")
        self.assertAlmostEqual(foreign["base_amount"], 990)
        self.assertEqual(foreign["fx_rate"], 1.1)
        self.assertEqual(foreign["fx_source"], "fx_rates_to_base")
        self.assertNotIn("excluded_reason", foreign)
        self.assertNotIn("RECON_FX_MISSING", foreign.get("findings", []))
        self.assertEqual(output["trust"]["findings"], [])
        context = output["trust"]["fx_context"]
        self.assertEqual(context["base_currency"], "USD")
        self.assertEqual(context["rates_to_base"], {"EUR": 1.1})
        self.assertEqual(context["rate_dates"], {"EUR": "2026-01-01"})
        self.assertEqual(context["sources"], {"EUR": "synthetic-cache"})
        self.assertEqual(context["snapshot_timestamp"], "2026-11-09T12:00:00Z")
        # HoldingTrustRecord does not invent a quote date; the lock carries it.
        self.assertNotIn("fx_timestamp", foreign)

    def test_metadata_fallback_does_not_invent_cached_fx_evidence(self) -> None:
        self.portfolio["holdings"][1]["metadata"] = {"fx_rate_to_base": 1.2}
        self.portfolio_path.write_text(json.dumps(self.portfolio))
        code, output, stderr = self.aggregate("--include-trust")

        self.assertEqual((code, stderr), (0, ""))
        self.assertAlmostEqual(output["portfolio_value_base"], 1180)
        foreign = output["trust"]["holdings"][1]
        self.assertEqual(foreign["fx_source"], "metadata.fx_rate_to_base")
        self.assertEqual(foreign["fx_rate"], 1.2)
        self.assertNotIn("excluded_reason", foreign)
        self.assertIn("TRUST_FX_FALLBACK_USED", foreign["findings"])
        self.assertNotIn("fx_timestamp", foreign)
        context = output["trust"]["fx_context"]
        self.assertEqual(context["rates_to_base"], {})
        self.assertEqual(context["rate_dates"], {})
        self.assertEqual(context["sources"], {})

    def test_missing_value_stays_unavailable_and_known_zero_stays_zero(self) -> None:
        # Diagnostic input deliberately lacks schema-required market_value.
        del self.portfolio["holdings"][1]["market_value"]
        self.portfolio["holdings"][0]["market_value"]["amount"] = 0
        self.assertTrue(validate_portfolio(self.portfolio))
        self.portfolio_path.write_text(json.dumps(self.portfolio))
        code, output, stderr = self.aggregate("--include-trust")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(output["portfolio_value_base"], 0)
        domestic, foreign = output["trust"]["holdings"]
        self.assertEqual(domestic["source_amount"], 0)
        self.assertEqual(domestic["base_amount"], 0)
        self.assertEqual(foreign["excluded_reason"], "missing_market_value")
        for field in ("source_amount", "source_currency", "base_amount", "fx_rate", "fx_source"):
            self.assertNotIn(field, foreign)
        # The existing calculation emits no finding for an absent market value.
        self.assertEqual(output["trust"]["findings"], [])

    def test_strict_failure_keeps_diagnostic_evidence_and_does_not_capture(self) -> None:
        bundle = self.root / "failed.zip"
        code, output, stderr = self.aggregate(
            "--include-trust", "--strict-quality", "--bundle", str(bundle),
        )

        self.assertEqual(code, 1)
        self.assertIn("strict mode", stderr)
        self.assertTrue(output["errors"])
        self.assertEqual(output["portfolio_value_base"], 100)
        foreign = output["trust"]["holdings"][1]
        self.assertEqual(foreign["holding_id"], "foreign")
        self.assertEqual(foreign["source_amount"], 900)
        self.assertEqual(foreign["source_currency"], "EUR")
        self.assertEqual(foreign["excluded_reason"], "fx_missing")
        self.assertIn("RECON_FX_MISSING", foreign["findings"])
        self.assertTrue(output["trust"]["findings"])
        self.assertFalse(bundle.exists())

    def test_default_compact_json_is_unchanged(self) -> None:
        self.portfolio["holdings"][1]["market_value"]["currency"] = "USD"
        self.portfolio_path.write_text(json.dumps(self.portfolio))
        code, compact, stderr = self.aggregate()

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(compact, {
            "base_currency": "USD",
            "portfolio_value_base": 1000,
            "by_asset_class": {"stocks": 1000},
            "warnings": [],
            "errors": [],
            "by_region": {"__unclassified__": 1000},
            "by_currency": {"USD": 1000},
            "by_duration": {"__unclassified__": 1000},
            "by_liquidity_tier": {"__unclassified__": 1000},
            "by_account": {"__unassigned__": 1000},
        })
        code, enriched, stderr = self.aggregate("--include-trust")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(enriched.pop("trust")["findings"], [])
        self.assertEqual(enriched, compact)

    def test_opt_in_uses_one_shared_calculation_and_does_not_mutate_inputs(self) -> None:
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with (
            patch("rikdom.analysis_bundle.aggregate_portfolio", wraps=aggregate_portfolio) as shared,
            patch("rikdom.cli.aggregate_portfolio", wraps=aggregate_portfolio) as cli_shared,
        ):
            code, _, stderr = self.aggregate("--include-trust")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(shared.call_count + cli_shared.call_count, 1)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.assertFalse((self.root / "out").exists())

    def test_bundle_captures_compact_result_and_replays_without_stdout_evidence(self) -> None:
        bundle = self.root / "aggregate.zip"
        original_portfolio, original_fx = self.portfolio_path.read_bytes(), self.fx_path.read_bytes()
        with patch("rikdom.analysis_bundle.aggregate_portfolio", wraps=aggregate_portfolio) as shared:
            code, enriched, stderr = self.aggregate("--include-trust", "--bundle", str(bundle))
        self.assertEqual(shared.call_count, 1)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.portfolio_path.read_bytes(), original_portfolio)
        self.assertEqual(self.fx_path.read_bytes(), original_fx)
        self.assertIn("trust", enriched)
        compact = {key: value for key, value in enriched.items() if key != "trust"}
        with zipfile.ZipFile(bundle) as archive:
            captured = json.loads(archive.read("analysis/result.json"))
            run = json.loads(archive.read("analysis/run.json"))
            manifest = json.loads(archive.read("rikdom-export.json"))
        self.assertEqual(captured, compact)
        self.assertEqual(manifest["format_version"], "3.0.0")
        self.assertEqual(run["method"], {"name": "aggregate", "version": "1.0.0"})
        self.assertEqual(set(run["parameters"]), {"strict", "fx_lock", "fx_warnings"})
        self.assertEqual(run["parameters"]["fx_lock"], enriched["trust"]["fx_context"])

        restored = self.root / "restored"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                "replay-export", "--bundle", str(bundle), "--restore-dir", str(restored),
            ])
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        replayed = json.loads(stdout.getvalue())
        self.assertEqual(replayed["status"], "reproduced")
        self.assertEqual(replayed["result"], compact)
        self.assertEqual(json.loads((restored / "analysis/result.json").read_text()), compact)


if __name__ == "__main__":
    unittest.main()
