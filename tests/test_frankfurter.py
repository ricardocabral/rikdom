from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from rikdom.fx import ensure_snapshot_fx_lock
from rikdom.plugin_engine.manifest import load_manifest
from rikdom.plugin_engine.runtime import load_plugin_instance
from rikdom.storage import load_jsonl


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "frankfurter"


def response(payload):
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


class FrankfurterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = load_plugin_instance(PLUGIN_DIR, load_manifest(PLUGIN_DIR))
        cls.module = sys.modules[type(cls.plugin).__module__]

    def query(self, **overrides):
        return self.plugin.connector_query(None, "daily-rates", {
            "base_currency": "BRL", "quote_currencies": ["USD"],
            "as_of_date": "2026-04-19", **overrides,
        })

    def test_query_normalizes_currencies_and_preserves_provider_date(self):
        payload = {"amount": 1.0, "base": "USD", "date": "2026-04-17",
                   "rates": {"BRL": 5.2}}
        with patch.object(self.module, "urlopen", return_value=response(payload)) as transport:
            actual = self.query(base_currency=" brl ", quote_currencies=[" usd ", "USD"])
        self.assertEqual(actual, {"USD": {
            "rate_to_base": 5.2, "as_of_date": "2026-04-17", "source": "frankfurter",
        }})
        transport.assert_called_once()
        outgoing = transport.call_args.args[0]
        url = urlsplit(outgoing.full_url)
        self.assertEqual((url.scheme, url.netloc, url.path),
                         ("https", "api.frankfurter.app", "/2026-04-19"))
        self.assertEqual(parse_qs(url.query), {"from": ["USD"], "to": ["BRL"]})
        self.assertEqual(transport.call_args.kwargs["timeout"], 10)
        headers = {key.lower(): value for key, value in outgoing.header_items()}
        self.assertIn("rikdom", headers["user-agent"])
        self.assertEqual(headers["accept"], "application/json")

    def test_provider_result_integrates_with_generic_cache(self):
        payload = {"amount": 1.0, "base": "USD", "date": "2026-04-17",
                   "rates": {"BRL": 5.2}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fx_rates.jsonl"
            with patch.object(self.module, "urlopen", return_value=response(payload)):
                lock, warnings = ensure_snapshot_fx_lock(
                    {"settings": {"base_currency": "BRL"}}, fx_history_path=path,
                    snapshot_timestamp="2026-04-19T12:00:00Z", auto_ingest=True,
                    extra_quote_currencies=["USD"],
                    fetcher=lambda **kwargs: self.plugin.connector_query(None, "daily-rates", kwargs),
                )
            self.assertEqual(warnings, [])
            self.assertEqual(lock["rate_dates"], {"USD": "2026-04-17"})
            self.assertEqual(lock["sources"], {"USD": "frankfurter"})
            self.assertEqual(load_jsonl(path)[0]["as_of_date"], "2026-04-17")

    def test_description_is_offline_and_detached(self):
        with patch.object(self.module, "urlopen") as transport:
            description = self.plugin.connector_describe(None)
            description["operations"].clear()
            fresh = self.plugin.connector_describe(None)
        transport.assert_not_called()
        self.assertEqual(fresh["provider"], "frankfurter")
        self.assertTrue(fresh["readOnly"])
        self.assertIn("daily-rates", fresh["operations"])

    def test_invalid_requests_fail_before_transport(self):
        invalid = [
            {"base_currency": "BR/L"}, {"quote_currencies": []},
            {"quote_currencies": "USD"}, {"quote_currencies": [None]},
            {"quote_currencies": ["US/"]}, {"quote_currencies": ["BRL"]},
            {"as_of_date": "2026-02-30"}, {"as_of_date": "20260419"},
            {"as_of_date": None}, {"unknown": "ignored"},
        ]
        for params in invalid:
            with self.subTest(params=params), patch.object(self.module, "urlopen") as transport:
                with self.assertRaises(self.module.FrankfurterError):
                    self.query(**params)
                transport.assert_not_called()
        with patch.object(self.module, "urlopen") as transport:
            with self.assertRaises(self.module.FrankfurterError):
                self.plugin.connector_query(None, "unknown", {})
            transport.assert_not_called()

    def test_invalid_provider_payloads_never_assert_a_requested_date(self):
        valid = {"amount": 1.0, "base": "USD", "date": "2026-04-17",
                 "rates": {"BRL": 5.2}}
        invalid = [None, [], {}, {**valid, "date": "2026-04-20"},
                   {**valid, "date": "2026-02-30"}, {**valid, "base": "EUR"},
                   {**valid, "amount": 2}, {**valid, "amount": True}]
        without_date = copy.deepcopy(valid)
        del without_date["date"]
        invalid.append(without_date)
        for rate in [0, -1, True, None, float("inf"), float("nan")]:
            invalid.append({**valid, "rates": {"BRL": rate}})
        invalid.extend([{**valid, "rates": []}, {**valid, "rates": {}}])
        for payload in invalid:
            with self.subTest(payload=payload):
                with patch.object(self.module, "urlopen", return_value=response(payload)):
                    with self.assertRaises(self.module.FrankfurterError):
                        self.query()

    def test_transport_and_json_failures_raise_provider_errors(self):
        errors = [URLError("connection failed"), TimeoutError("timeout"),
                  HTTPError("https://api.frankfurter.app", 429, "rate limited", {}, None)]
        for error in errors:
            with self.subTest(error=error):
                with patch.object(self.module, "urlopen", side_effect=error):
                    with self.assertRaises(self.module.FrankfurterError):
                        self.query()
        with patch.object(self.module, "urlopen", return_value=io.BytesIO(b"invalid-json")):
            with self.assertRaises(self.module.FrankfurterError):
                self.query()


if __name__ == "__main__":
    unittest.main()
