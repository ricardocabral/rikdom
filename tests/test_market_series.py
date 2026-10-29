"""Contract and replay behavior: no clock, provider, or canonical storage involved."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from rikdom.market_series import load_market_series


def observation(**changes):
    return {"id": "p1", "effective_at": "2026-01-02T16:00:00Z",
            "retrieved_at": "2026-01-02T17:00:00Z", "source": "manual:example",
            "value": 100, "currency": "USD", "supersedes": None, **changes}


def document():
    return {"contract_version": "1.0", "series": [
        {"id": "example-price", "kind": "price", "currency": "USD",
         "instrument": {"namespace": "EXAMPLE", "id": "DEMO", "currency": "USD"},
         "adjustment": "unadjusted",
         "coverage": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-31T23:59:59Z"},
         "license": {"name": "CC0-1.0", "uri": "https://creativecommons.org/publicdomain/zero/1.0/"},
         "observations": [observation()]},
        {"id": "example-fx", "kind": "fx", "currency": "BRL",
         "currency_pair": {"base": "USD", "quote": "BRL"},
         "adjustment": "not_applicable",
         "coverage": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-31T23:59:59Z"},
         "license": {"name": "CC0-1.0", "uri": "https://creativecommons.org/publicdomain/zero/1.0/"},
         "observations": [observation(id="f1", value=5.25, currency="BRL")]}]}


class MarketSeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "series.json"

    def load(self, payload=None):
        self.path.write_text(json.dumps(document() if payload is None else payload), encoding="utf-8")
        return load_market_series(self.path)

    def query(self, store, **changes):
        return store.lookup("example-price", as_of="2026-01-03T16:00:00Z", max_age_seconds=86400, **changes)

    def test_manual_sample_replays_price_and_fx_without_modification(self):
        path = Path(__file__).resolve().parents[1] / "data-sample" / "market-series.json"
        before = path.read_bytes()
        for _ in range(2):
            store = load_market_series(path)
            price = self.query(store)
            self.assertEqual(price["observation"]["value"], 101)
            self.assertEqual(price["superseded"][0]["value"], 100)
            self.assertEqual(price["observation"]["source"], "manual:synthetic-correction")
            fx = store.lookup("example-fx", as_of="2026-01-03T16:00:00Z", max_age_seconds=86400)
            self.assertEqual(fx["observation"]["value"], 5.25)
            self.assertEqual(fx["series"]["license"]["name"], "CC0-1.0")
        self.assertEqual(path.read_bytes(), before)

    def test_exact_age_boundary_and_provenance(self):
        result = self.query(self.load())
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["age_seconds"], 86400)
        self.assertEqual(result["observation"], observation())
        self.assertEqual(result["series"]["license"]["name"], "CC0-1.0")
        self.assertEqual(result["series"]["instrument"]["namespace"], "EXAMPLE")
        self.assertEqual(result["superseded"], [])

    def test_directional_fx_and_repeated_detached_replay(self):
        store = self.load()
        before = self.path.read_bytes()
        first = store.lookup("example-fx", as_of="2026-01-02T16:00:00Z", max_age_seconds=0)
        self.assertEqual(first["status"], "available")
        self.assertEqual(first["observation"]["value"], 5.25)
        self.assertEqual(first["series"]["currency_pair"], {"base": "USD", "quote": "BRL"})
        again = store.lookup("example-fx", as_of="2026-01-02T16:00:00Z", max_age_seconds=0)
        self.assertEqual(first, again)
        first["observation"]["value"] = 999
        first["series"]["license"]["name"] = "mutated"
        self.assertEqual(store.lookup("example-fx", as_of="2026-01-02T16:00:00Z", max_age_seconds=0), again)
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_retains_selected_evidence(self):
        result = self.load().lookup("example-price", as_of="2026-01-04T16:00:00Z", max_age_seconds=86400)
        self.assertEqual((result["status"], result["reason"], result["age_seconds"]), ("stale", "maximum_age_exceeded", 172800))
        self.assertEqual(result["observation"]["id"], "p1")

    def test_missing_unknown_future_and_coverage_diagnostics(self):
        store = self.load()
        for sid, as_of, reason in [
            ("unknown", "2026-01-03T00:00:00Z", "unknown_series"),
            ("example-price", "2026-01-01T00:00:00Z", "no_eligible_observation"),
            ("example-price", "2026-02-01T00:00:00Z", "outside_declared_coverage"),
        ]:
            with self.subTest(reason=reason):
                result = store.lookup(sid, as_of=as_of, max_age_seconds=86400)
                self.assertEqual((result["status"], result["reason"], result["observation"]), ("missing", reason, None))

    def test_latest_effective_wins_not_latest_retrieval(self):
        payload = document()
        payload["series"][0]["observations"] += [
            observation(id="p2", effective_at="2026-01-03T16:00:00Z", retrieved_at="2026-01-03T17:00:00Z", value=110),
            observation(id="p1r", retrieved_at="2026-01-04T17:00:00Z", value=101, supersedes="p1")]
        self.assertEqual(self.query(self.load(payload))["observation"]["value"], 110)

    def test_corrections_traceable_and_knowledge_cutoff_is_inclusive(self):
        payload = document()
        payload["series"][0]["observations"].insert(0, observation(id="p1r", retrieved_at="2026-01-04T17:00:00Z", value=101, supersedes="p1"))
        store = self.load(payload)
        latest = self.query(store)
        self.assertEqual(latest["observation"]["value"], 101)
        self.assertEqual(latest["superseded"], [observation()])
        original = self.query(store, retrieved_before="2026-01-02T17:00:00Z")
        self.assertEqual(original["observation"]["value"], 100)
        self.assertEqual(original["superseded"], [])
        self.assertEqual(self.query(store, retrieved_before="2026-01-02T16:00:00Z")["status"], "missing")
        payload["series"].reverse()
        payload["series"][1]["observations"].reverse()
        self.assertEqual(self.query(self.load(payload)), latest)

    def test_rejects_ambiguous_duplicate_and_invalid_revision_chains(self):
        cases = [observation(), observation(id="other", value=101),
                 observation(id="r", supersedes="absent", retrieved_at="2026-01-04T00:00:00Z"),
                 observation(id="r", supersedes="p1"),
                 observation(id="r", supersedes="p1", effective_at="2026-01-03T16:00:00Z", retrieved_at="2026-01-04T00:00:00Z")]
        for extra in cases:
            payload = document()
            payload["series"][0]["observations"].append(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.load(payload)
        payload = document()
        payload["series"][0]["observations"] += [
            observation(id="r1", supersedes="p1", retrieved_at="2026-01-04T00:00:00Z"),
            observation(id="r2", supersedes="p1", retrieved_at="2026-01-05T00:00:00Z")]
        with self.assertRaises(ValueError):
            self.load(payload)

    def test_rejects_invalid_numbers_timestamps_and_mismatched_currency(self):
        invalid = {"value": [True, False, 0, -1, float("nan"), float("inf"), -float("inf"), "100", 10**400],
                   "effective_at": ["2026-02-30T00:00:00Z", "2026-01-02", "2026-01-02T00:00:00", "2026-01-02T00:00:00+03:00", "2026-01-02T24:00:00Z"],
                   "retrieved_at": ["2026-01-01T00:00:00Z", "2026-99-02T00:00:00Z"],
                   "currency": ["BRL", "usd", "US", None], "source": ["", "  ", None]}
        for field, values in invalid.items():
            for value in values:
                payload = document()
                payload["series"][0]["observations"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.load(payload)

    def test_rejects_unknown_versions_fields_identity_coverage_and_license(self):
        cases = []
        for version in [None, 1, "2.0"]:
            p = document()
            p["contract_version"] = version
            cases.append(p)
        for field, value in [("adjustment", "unknown"), ("license", {}), ("coverage", {"start": "2026-01-31T00:00:00Z", "end": "2026-01-01T00:00:00Z"}),
                             ("instrument", {"namespace": "EXAMPLE", "id": "DEMO", "currency": "BRL"})]:
            p = document()
            p["series"][0][field] = value
            cases.append(p)
        p = document()
        p["series"][0]["observations"][0]["oops"] = 1
        cases.append(p)
        p = document()
        p["series"][1]["currency_pair"]["quote"] = "USD"
        cases.append(p)
        p = document()
        p["series"].append(copy.deepcopy(p["series"][0]))
        cases.append(p)
        for p in cases:
            with self.subTest(payload=p), self.assertRaises(ValueError):
                self.load(p)

    def test_rejects_duplicate_json_keys_and_malformed_json(self):
        for text in ['{"contract_version":"2.0","contract_version":"1.0","series":[]}', '{oops', '[]']:
            self.path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_market_series(self.path)

    def test_query_requires_utc_and_explicit_finite_nonnegative_age(self):
        store = self.load()
        for age in [True, -1, float("nan"), float("inf"), "1", 10**400]:
            with self.subTest(age=age), self.assertRaises(ValueError):
                store.lookup("example-price", as_of="2026-01-03T00:00:00Z", max_age_seconds=age)
        for as_of in ["2026-01-03", "2026-01-03T00:00:00", "2026-02-30T00:00:00Z"]:
            with self.subTest(as_of=as_of), self.assertRaises(ValueError):
                store.lookup("example-price", as_of=as_of, max_age_seconds=1)
        with self.assertRaises(ValueError):
            self.query(store, retrieved_before="2026-01-03")
