import copy
import unittest

from rikdom.import_preflight import build_preflight_report
from rikdom.plugins import merge_import_diagnostics


def diagnostics(fingerprint="doc-a"):
    return {"version": 1, "document_fingerprint": fingerprint, "history_coverage": [{"scope": "opaque-account", "status": "partial", "event_types": ["buy", "sell"], "reasons": ["Opening position unknown"]}], "unsupported_events": []}


def event(name, document="doc-a"):
    return {"id": name, "idempotency_key": name, "event_type": "buy", "status": "posted", "effective_at": "2026-01-02T12:00:00Z", "metadata": {"rikdom_source_identity": {"version": 1, "scope": "opaque-account", "document_fingerprint": document, "signature": "same-trade", "occurrence": 0, "kind": "anonymous"}}}


class ImportDiagnosticsTests(unittest.TestCase):
    def test_coverage_survives_reimport_without_duplicate_evidence(self):
        p = {"holdings": [], "extensions": {"custom": {"keep": True}}}
        payload = {"provider": "source", "metadata": {"rikdom_import_diagnostics": diagnostics()}}
        merge_import_diagnostics(p, payload)
        merge_import_diagnostics(p, payload)
        statements = p["extensions"]["rikdom_import_diagnostics"]["statements"]
        self.assertEqual(len(statements), 1)
        self.assertEqual(next(iter(statements.values()))["history_coverage"][0]["status"], "partial")
        self.assertTrue(p["extensions"]["custom"]["keep"])

    def test_coverage_dates_are_not_locale_guessed(self):
        d = diagnostics()
        d["history_coverage"][0].update(status="complete", **{"from": "01/02/2026", "through": "2026-02-28"})
        report = build_preflight_report({"holdings": []}, {"metadata": {"rikdom_import_diagnostics": d}})
        self.assertFalse(report["ok"])

    def test_anonymous_overlap_blocks_other_documents_but_not_replay(self):
        p = {"holdings": [], "activities": [event("a")]}
        self.assertTrue(build_preflight_report(p, {"activities": [event("a")]})["ok"])
        incoming = event("b", "doc-b")
        report = build_preflight_report(p, {"activities": [incoming]})
        self.assertFalse(report["ok"])
        self.assertIn("AMBIGUOUS_IMPORT_IDENTITY", [i["code"] for i in report["issues"]])

    def test_reviewed_overlap_requires_real_existing_identities(self):
        p = {"holdings": [], "activities": [event("a")]}
        incoming = event("b", "doc-b")
        incoming["metadata"]["rikdom_source_identity"]["kind"] = "reviewed"
        resolution = {"scope": "opaque-account", "document_fingerprint": "doc-b", "existing_activity_ids": ["a"], "new_activity_ids": ["b"], "reason": "Compared source rows"}
        payload = {"activities": [event("a"), incoming], "metadata": {"rikdom_import_diagnostics": {**diagnostics("doc-b"), "identity_resolution": resolution}}}
        self.assertTrue(build_preflight_report(p, payload)["ok"])
        bad = copy.deepcopy(payload)
        bad["metadata"]["rikdom_import_diagnostics"]["identity_resolution"]["existing_activity_ids"] = ["missing"]
        self.assertFalse(build_preflight_report(p, bad)["ok"])

    def test_same_document_occurrence_cannot_change_identity(self):
        p = {"holdings": [], "activities": [event("a")]}
        self.assertFalse(build_preflight_report(p, {"activities": [event("new-id")]})["ok"])

    def test_reviewed_new_identity_cannot_overwrite_an_unrelated_event(self):
        unrelated = event("b", "unrelated-doc")
        unrelated["metadata"]["rikdom_source_identity"]["signature"] = "unrelated"
        p = {"holdings": [], "activities": [event("a"), unrelated]}
        incoming = event("b", "doc-b")
        incoming["metadata"]["rikdom_source_identity"]["kind"] = "reviewed"
        resolution = {"scope": "opaque-account", "document_fingerprint": "doc-b", "existing_activity_ids": ["a"], "new_activity_ids": ["b"], "reason": "Reviewed"}
        self.assertFalse(build_preflight_report(p, {"activities": [event("a"), incoming], "metadata": {"rikdom_import_diagnostics": {**diagnostics("doc-b"), "identity_resolution": resolution}}})["ok"])


if __name__ == "__main__":
    unittest.main()
