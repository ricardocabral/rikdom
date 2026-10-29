from __future__ import annotations

import contextlib
import copy
import io
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rikdom.performance import compute_performance

START = "2026-01-01T00:00:00Z"
MID = "2026-01-06T00:00:00Z"
END = "2026-01-11T00:00:00Z"


def snapshots(start=100, end=176):
    return [
        {
            "timestamp": START,
            "base_currency": "BRL",
            "totals": {"portfolio_value_base": start},
        },
        {
            "timestamp": END,
            "base_currency": "BRL",
            "totals": {"portfolio_value_base": end},
        },
    ]


def flow(amount=50, when=MID, kind="contribution", currency="BRL"):
    return {
        "id": "synthetic",
        "event_type": kind,
        "effective_at": when,
        "money": {"amount": amount, "currency": currency},
    }


def evidence(pre=110, post=160, when=MID):
    return {
        "version": 1,
        "scope": "portfolio",
        "base_currency": "BRL",
        "rounding_tolerance_base": 0.01,
        "valuations": [
            {
                "timestamp": when,
                "base_currency": "BRL",
                "pre_flow_value_base": pre,
                "post_flow_value_base": post,
                "source": "synthetic independently valued boundary",
            }
        ],
    }


class LinkedTWRTests(unittest.TestCase):
    def compute(self, acts=None, sidecar=None, snaps=None, **kwargs):
        return compute_performance(
            snapshots() if snaps is None else snaps,
            [flow()] if acts is None else acts,
            base_currency="BRL",
            flow_valuations=sidecar,
            **kwargs,
        )

    def test_contribution_links_21_percent_preserving_legacy_dietz(self):
        result = self.compute(sidecar=evidence())
        self.assertEqual(result.linked_twr_pct, 21.0)
        self.assertEqual(result.twr_return_pct, 21.0)
        self.assertEqual(result.twr_pct, 20.8)
        self.assertEqual(result.twr_method, "linked_subperiod")
        self.assertIsNone(result.twr_fallback_reason)
        self.assertEqual(result.twr_return_basis, "period")
        self.assertEqual(result.mwr_return_basis, "annualized_365_day")
        self.assertIsNotNone(result.mwr_pct)

    def test_withdrawal_links_21_percent(self):
        result = self.compute(
            [flow(50, kind="withdrawal")], evidence(110, 60), snapshots(end=66)
        )
        self.assertEqual(result.linked_twr_pct, 21.0)

    def test_same_instant_flows_aggregate_signed_amounts(self):
        acts = [flow(80), dict(flow(30, kind="withdrawal"), id="second")]
        self.assertEqual(self.compute(acts, evidence()).linked_twr_pct, 21.0)

    def test_multiple_subperiods_link(self):
        sidecar = evidence()
        row = copy.deepcopy(sidecar["valuations"][0])
        row.update(
            timestamp="2026-01-08T00:00:00Z",
            pre_flow_value_base=176,
            post_flow_value_base=156,
        )
        sidecar["valuations"].append(row)
        acts = [flow(), dict(flow(20, row["timestamp"], "withdrawal"), id="second")]
        self.assertEqual(
            self.compute(acts, sidecar, snapshots(end=171.6)).linked_twr_pct, 33.1
        )

    def test_no_flow_bookend_and_internal_events(self):
        acts = [flow(kind=kind) for kind in ("buy", "sell", "dividend", "split")]
        result = self.compute(acts, snaps=snapshots(end=110))
        self.assertEqual(result.twr_method, "bookend_ratio")
        self.assertEqual(result.twr_return_pct, 10.0)
        self.assertEqual(result.cashflow_count, 0)

    def test_missing_evidence_uses_labeled_dietz_even_with_daily_snapshots(self):
        snaps = snapshots()
        snaps.insert(1, {"timestamp": MID, "totals": {"portfolio_value_base": 160}})
        result = self.compute(snaps=snaps)
        self.assertEqual(result.twr_method, "modified_dietz")
        self.assertEqual(result.twr_return_pct, 20.8)
        self.assertIsNone(result.linked_twr_pct)
        self.assertIn("missing", result.twr_fallback_reason.lower())

    def test_inconsistent_evidence_falls_back(self):
        result = self.compute(sidecar=evidence(110, 159))
        self.assertEqual(result.twr_method, "modified_dietz")
        self.assertIn("cashflow", result.twr_fallback_reason.lower())

    def test_tolerance_is_absolute_base_currency(self):
        self.assertEqual(
            self.compute(sidecar=evidence(110, 160.005)).twr_method, "linked_subperiod"
        )
        self.assertEqual(
            self.compute(sidecar=evidence(110, 160.02)).twr_method, "modified_dietz"
        )

    def test_boundaries_are_start_pre_flow_end_post_flow(self):
        for when, pre, post, start, end, expected in [
            (START, 100, 150, 100, 165, 10.0),
            (END, 110, 160, 100, 160, 10.0),
        ]:
            with self.subTest(when=when):
                self.assertEqual(
                    self.compute(
                        [flow(50, when)],
                        evidence(pre, post, when),
                        snapshots(start, end),
                    ).linked_twr_pct,
                    expected,
                )
        result = self.compute(
            [flow(50, START)], evidence(100, 150, START), snapshots(150, 165)
        )
        self.assertEqual(result.twr_method, "modified_dietz")
        self.assertIn("start", result.twr_fallback_reason.lower())

    def test_missing_one_boundary_and_unmatched_boundary_fall_back(self):
        acts = [flow(), dict(flow(10, END), id="second")]
        self.assertEqual(self.compute(acts, evidence()).twr_method, "modified_dietz")
        self.assertEqual(self.compute([], evidence()).twr_method, "modified_dietz")

    def test_losses_zero_and_negative_capital(self):
        self.assertEqual(
            self.compute([], snaps=snapshots(end=0)).twr_return_pct, -100.0
        )
        self.assertEqual(
            self.compute([], snaps=snapshots(end=80)).twr_return_pct, -20.0
        )
        for start, end in [(0, 110), (-100, 110), (100, -10)]:
            with self.subTest(start=start, end=end):
                result = self.compute([], snaps=snapshots(start, end))
                self.assertEqual(result.twr_method, "unavailable")
                self.assertIsNone(result.twr_return_pct)
        result = self.compute(
            [flow(110, kind="withdrawal")], evidence(110, 0), snapshots(end=10)
        )
        self.assertEqual(result.twr_method, "unavailable")

    def test_nonfinite_bookends_and_flows_are_unavailable(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                result = self.compute([], snaps=snapshots(end=value))
                self.assertEqual(result.twr_method, "unavailable")
                self.assertIsNone(result.mwr_pct)
                result = self.compute([flow(value)], evidence())
                self.assertEqual(result.twr_method, "unavailable")
                self.assertIsNone(result.mwr_pct)

    def test_skipped_foreign_flows_and_undated_fx_are_visibly_approximate(self):
        result = self.compute([flow(currency="USD")], evidence())
        self.assertEqual(result.twr_method, "modified_dietz")
        self.assertTrue(any("FX" in warning for warning in result.warnings))
        result = self.compute(
            [flow(10, currency="USD")], evidence(), fx_rates_to_base={"USD": 5}
        )
        self.assertEqual(result.twr_method, "modified_dietz")
        self.assertTrue(
            any("approximate" in warning.lower() for warning in result.warnings)
        )

    def test_transfers_do_not_invent_pairing(self):
        acts = [
            flow(50, kind="transfer_in"),
            dict(flow(50, kind="transfer_out"), id="second"),
        ]
        result = self.compute(acts, evidence(110, 110), snapshots(end=121))
        self.assertEqual(result.twr_method, "modified_dietz")
        self.assertIn("transfer", result.twr_fallback_reason.lower())

    def test_malformed_external_flow_never_claims_exact_bookend_return(self):
        for mutation in (
            {"money": {}},
            {"money": {"amount": True, "currency": "BRL"}},
            {"money": {"amount": 50, "currency": ""}},
            {"effective_at": "unknown"},
        ):
            with self.subTest(mutation=mutation):
                activity = dict(flow(), **mutation)
                result = self.compute([activity])
                self.assertNotEqual(result.twr_method, "bookend_ratio")
                self.assertTrue(result.warnings)

    def test_snapshot_currency_mismatch_cannot_claim_linked_return(self):
        snaps = snapshots()
        snaps[0]["base_currency"] = "USD"
        result = self.compute(sidecar=evidence(), snaps=snaps)
        self.assertEqual(result.twr_method, "unavailable")
        self.assertIsNone(result.mwr_pct)

    def test_negative_evidence_capital_is_unavailable(self):
        result = self.compute(sidecar=evidence(-10, 40))
        self.assertEqual(result.twr_method, "unavailable")
        self.assertIsNone(result.twr_return_pct)

    def test_evidence_outside_window_is_not_used(self):
        sidecar = evidence()
        sidecar["valuations"].append(
            dict(sidecar["valuations"][0], timestamp="2025-12-01T00:00:00Z")
        )
        self.assertEqual(self.compute(sidecar=sidecar).linked_twr_pct, 21.0)

    def test_missing_bookends_are_unavailable(self):
        result = self.compute([], evidence(), [])
        self.assertEqual(result.twr_method, "unavailable")

    def test_malformed_transfer_dates_warn_without_crashing(self):
        for when in (None, 123, {}, []):
            with self.subTest(when=when):
                result = self.compute([flow(when=when, kind="transfer_in")])
                self.assertIn(result.twr_method, ("modified_dietz", "unavailable"))
                self.assertTrue(
                    any("effective_at" in warning for warning in result.warnings)
                )
                self.assertIsNone(result.linked_twr_pct)

    def test_transfer_spelling_does_not_bypass_unresolved_identity(self):
        for kind in (
            "transfer_in",
            "TRANSFER_IN",
            " TRANSFER_IN ",
            "transfer_out",
            " TRANSFER_OUT ",
        ):
            with self.subTest(kind=kind):
                is_in = kind.strip().lower() == "transfer_in"
                result = self.compute(
                    [flow(kind=kind)],
                    evidence(110, 160 if is_in else 60),
                    snapshots(end=176 if is_in else 66),
                )
                self.assertEqual(result.twr_method, "modified_dietz")
                self.assertIn("transfer", result.twr_fallback_reason.lower())
                self.assertIsNone(result.linked_twr_pct)

    def test_out_of_float_range_numbers_are_handled_at_input_boundaries(self):
        huge = 10**400
        for field in (
            "rounding_tolerance_base",
            "pre_flow_value_base",
            "post_flow_value_base",
        ):
            doc = evidence()
            if field == "rounding_tolerance_base":
                doc[field] = huge
            else:
                doc["valuations"][0][field] = huge
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "flow-valuations"),
            ):
                self.compute(sidecar=doc)
        with self.subTest(boundary="snapshot"):
            result = self.compute([], snaps=snapshots(end=huge))
            self.assertEqual(result.twr_method, "unavailable")
        with self.subTest(boundary="flow"):
            result = self.compute([flow(huge)], evidence())
            self.assertEqual(result.twr_method, "unavailable")
        for kwargs in ({"fx_rates_to_base": {"USD": huge}}, {}):
            activity = flow(currency="USD")
            activity["metadata"] = {"fx_rate_to_base": huge}
            with self.subTest(kwargs=kwargs):
                result = self.compute([activity], evidence(), **kwargs)
                self.assertIn(result.twr_method, ("modified_dietz", "unavailable"))
                self.assertTrue(result.warnings)
        from rikdom.performance import external_cashflow_currencies

        self.assertEqual(
            external_cashflow_currencies([flow(huge, currency="USD")], "BRL"), []
        )

    def test_nonrepresentable_return_arithmetic_and_percent_are_unavailable(self):
        cases = [
            ([], None, snapshots(1e-300, 1e300)),
            ([], None, snapshots(1, 1e307)),
            ([flow(0)], evidence(1e307, 1e307), snapshots(1, 1e307)),
        ]
        for acts, sidecar, snaps in cases:
            with self.subTest(acts=acts, snaps=snaps):
                result = self.compute(acts, sidecar, snaps)
                self.assertEqual(result.twr_method, "unavailable")
                self.assertIsNone(result.twr_return_pct)
                self.assertIsNone(result.linked_twr_pct)
                self.assertTrue(result.twr_fallback_reason)
                json.dumps(asdict(result), allow_nan=False)

    def test_aggregate_flow_overflow_is_unavailable_and_serializable(self):
        result = self.compute([flow(1e308), dict(flow(1e308), id="second")])
        self.assertEqual(result.twr_method, "unavailable")
        self.assertIsNone(result.twr_return_pct)
        self.assertIsNone(result.net_external_cashflow_base)
        json.dumps(asdict(result), allow_nan=False)

    def test_strict_versioned_sidecar_validation(self):
        cases = []
        for key, value in [
            ("version", 2),
            ("version", True),
            ("scope", "account"),
            ("base_currency", "USD"),
            ("rounding_tolerance_base", -1),
            ("rounding_tolerance_base", float("nan")),
            ("valuations", {}),
        ]:
            doc = evidence()
            doc[key] = value
            cases.append(doc)
        for key, value in [
            ("timestamp", "2026-01-06"),
            ("source", ""),
            ("base_currency", "USD"),
            ("pre_flow_value_base", True),
            ("post_flow_value_base", float("inf")),
            ("unexpected", 1),
        ]:
            doc = evidence()
            doc["valuations"][0][key] = value
            cases.append(doc)
        duplicate = evidence()
        duplicate["valuations"].append(
            dict(duplicate["valuations"][0], timestamp="2026-01-06T01:00:00+01:00")
        )
        cases.append(duplicate)
        missing = evidence()
        del missing["valuations"][0]["source"]
        cases.append(missing)
        for doc in cases:
            with (
                self.subTest(doc=doc),
                self.assertRaisesRegex(ValueError, "flow.valuations"),
            ):
                self.compute(sidecar=doc)


class LinkedTWRCLITests(unittest.TestCase):
    def test_cli_reads_sidecar_and_discloses_method_without_mutating_files(self):
        from rikdom.cli import main

        with TemporaryDirectory() as temp:
            root = Path(temp)
            portfolio = json.loads(Path("data-sample/portfolio.json").read_text())
            portfolio["activities"] = [flow()]
            (root / "portfolio.json").write_text(json.dumps(portfolio))
            (root / "snapshots.jsonl").write_text(
                "\n".join(json.dumps(row) for row in snapshots()) + "\n"
            )
            (root / "evidence.json").write_text(json.dumps(evidence()))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            args = [
                "performance",
                "--portfolio",
                str(root / "portfolio.json"),
                "--snapshots",
                str(root / "snapshots.jsonl"),
                "--flow-valuations",
                str(root / "evidence.json"),
            ]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(args)
            self.assertEqual(rc, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["twr_return_pct"], 21.0)
            self.assertEqual(result["twr_method"], "linked_subperiod")
            self.assertEqual(result["mwr_return_basis"], "annualized_365_day")
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                rc = main(args + ["--by", "account"])
            self.assertEqual(rc, 1)
            self.assertIn("portfolio", error.getvalue())
            (root / "evidence.json").write_text("{broken")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                rc = main(args)
            self.assertEqual(rc, 1)
            self.assertIn("flow-valuations", error.getvalue())

    def test_cli_rejects_ambiguous_or_out_of_range_flow_evidence(self):
        from rikdom.cli import main

        with TemporaryDirectory() as temp:
            root = Path(temp)
            portfolio = json.loads(Path("data-sample/portfolio.json").read_text())
            portfolio["activities"] = [flow()]
            (root / "portfolio.json").write_text(json.dumps(portfolio))
            (root / "snapshots.jsonl").write_text(
                "\n".join(json.dumps(row) for row in snapshots()) + "\n"
            )
            args = [
                "performance",
                "--portfolio",
                str(root / "portfolio.json"),
                "--snapshots",
                str(root / "snapshots.jsonl"),
                "--flow-valuations",
                str(root / "evidence.json"),
            ]
            original = json.dumps(evidence())
            payloads = [
                original.replace(
                    '"pre_flow_value_base": 110',
                    '"pre_flow_value_base": 999, "pre_flow_value_base": 110',
                ),
                original.replace('"version": 1', '"version": 2, "version": 1'),
                original.replace(
                    '"rounding_tolerance_base": 0.01',
                    '"rounding_tolerance_base": ' + str(10**400),
                ),
            ]
            for payload in payloads:
                with self.subTest(payload=payload):
                    (root / "evidence.json").write_text(payload)
                    out, error = io.StringIO(), io.StringIO()
                    with (
                        contextlib.redirect_stdout(out),
                        contextlib.redirect_stderr(error),
                    ):
                        rc = main(args)
                    self.assertEqual(rc, 1)
                    self.assertEqual(out.getvalue(), "")
                    self.assertIn("flow-valuations", error.getvalue())
