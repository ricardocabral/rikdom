from __future__ import annotations

import io
import json
import unittest
from email.message import Message
from unittest.mock import patch
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler

from rikdom.plugin_engine.manifest import load_manifest
from rikdom.plugin_engine.runtime import load_plugin_instance

_PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "brapi"
_plugin = load_plugin_instance(_PLUGIN_DIR, load_manifest(_PLUGIN_DIR))
_module = sys.modules[type(_plugin).__module__]
BrapiError = _module.BrapiError


def fetch_brapi_data(operation, symbols, *, parameters=None):
    return _plugin.connector_query(
        None, operation, {"symbols": symbols, **(parameters or {})}
    )


def response(payload: object) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def http_error(status: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(
        "https://brapi.dev/api/v2/stocks/quote", status, "failed", headers, None
    )


class BrapiTests(unittest.TestCase):
    def setUp(self) -> None:
        token = patch.dict("os.environ", {"BRAPI_TOKEN": "test-secret-token"})
        token.start()
        self.addCleanup(token.stop)

    def test_quote_normalizes_and_batches_symbols_with_bearer_auth(self) -> None:
        payload = {
            "results": [
                {
                    "symbol": "RENAMED3",
                    "regularMarketPrice": None,
                    "nested": {"value": None},
                    "history": [None],
                },
            ],
            "warnings": ["symbol changed"],
            "errors": [{"symbol": "UNKNOWN3", "message": "not found"}],
        }
        with patch.object(
            _module, "urlopen", return_value=response(payload)
        ) as request:
            actual = fetch_brapi_data("quote", [" petr4 ", "VALE3", "PETR4"])
        self.assertEqual(actual, payload)
        request.assert_called_once()
        outgoing = request.call_args.args[0]
        url = urlsplit(outgoing.full_url)
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.netloc, "brapi.dev")
        self.assertEqual(url.path, "/api/v2/stocks/quote")
        self.assertEqual(parse_qs(url.query)["symbols"], ["PETR4,VALE3"])
        headers = {name.lower(): value for name, value in outgoing.header_items()}
        self.assertEqual(headers["authorization"], "Bearer test-secret-token")
        self.assertNotIn("test-secret-token", outgoing.full_url)

    def test_all_operations_use_expected_endpoints_and_symbol_query(self) -> None:
        operations = {
            "historical": ("stocks/historical", "PETR4", "symbols"),
            "dividends": ("stocks/dividends", "PETR4", "symbols"),
            "fii-indicators": ("fii/indicators", "HGLG11", "symbols"),
            "fii-historical": ("fii/historical", "HGLG11", "symbols"),
            "fii-dividends": ("fii/dividends", "HGLG11", "symbols"),
            "currency": ("currency", "USD-BRL", "currency"),
            "currency-historical": ("currency/historical", "USD-BRL", "currency"),
            "macro": ("macro", "ipca", "symbols"),
            "macro-latest": ("macro/latest", "ipca", "symbols"),
        }
        for operation, (path, symbol, query_key) in operations.items():
            with self.subTest(operation=operation):
                with patch.object(
                    _module, "urlopen", return_value=response({})
                ) as request:
                    self.assertEqual(
                        fetch_brapi_data(operation, [f" {symbol} ", symbol]), {}
                    )
                request.assert_called_once()
                url = urlsplit(request.call_args.args[0].full_url)
                self.assertEqual(url.path, f"/api/v2/{path}")
                self.assertEqual(parse_qs(url.query)[query_key], [symbol])

    def test_macro_symbols_are_lowercase(self) -> None:
        with patch.object(_module, "urlopen", return_value=response({})) as request:
            fetch_brapi_data("macro", [" IPCA ", "ipca", "SELIC"])
        query = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual(query["symbols"], ["ipca,selic"])

    def test_historical_preserves_openapi_parameter_names(self) -> None:
        parameters = {
            "startDate": "2026-01-01",
            "endDate": "2026-02-01",
            "interval": "1d",
        }
        with patch.object(_module, "urlopen", return_value=response({})) as request:
            fetch_brapi_data("historical", ["PETR4"], parameters=parameters)
        query = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        for name, value in parameters.items():
            self.assertEqual(query[name], [value])

    def test_redirect_does_not_forward_authorization(self) -> None:
        with patch.object(_module, "urlopen", return_value=response({})) as request:
            fetch_brapi_data("quote", ["PETR4"])
        outgoing = request.call_args.args[0]
        redirected = HTTPRedirectHandler().redirect_request(
            outgoing, None, 302, "Found", {}, "https://other.example/quote"
        )
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_connector_accepts_comma_delimited_symbols(self) -> None:
        with patch.object(_module, "urlopen", return_value=response({})) as request:
            _plugin.connector_query(None, "quote", {"symbols": "petr4, VALE3,petr4"})
        query = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual(query["symbols"], ["PETR4,VALE3"])

    def test_describe_is_offline_and_exposes_no_secret(self) -> None:
        with patch.object(_module, "urlopen") as request:
            description = _plugin.connector_describe(None)
        request.assert_not_called()
        self.assertEqual(description["provider"], "brapi")
        self.assertEqual(description["auth"]["environment"], "BRAPI_TOKEN")
        self.assertNotIn("test-secret-token", json.dumps(description))

    def test_documented_parameters_reach_provider(self) -> None:
        cases = (
            ("dividends", {"sortBy": "rate", "includeRaw": "true"}),
            ("fii-dividends", {"sortBy": "paymentDate"}),
            ("currency-historical", {"limit": 12}),
            ("macro", {"limit": 10, "sortOrder": "desc"}),
        )
        for operation, parameters in cases:
            with self.subTest(operation=operation):
                with patch.object(
                    _module, "urlopen", return_value=response({})
                ) as request:
                    fetch_brapi_data(
                        operation,
                        ["IPCA" if operation == "macro" else "TEST"],
                        parameters=parameters,
                    )
                query = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
                for name, value in parameters.items():
                    self.assertEqual(query[name], [str(value)])

    def test_invalid_operation_parameters_fail_before_network(self) -> None:
        cases = (
            ("historical", {"range": "forever"}),
            ("historical", {"interval": "12h"}),
            ("historical", {"includeRaw": "yes"}),
            ("historical", {"startDate": "2026-02-30"}),
            ("historical", {"startDate": "2026-02-01", "endDate": "2026-01-01"}),
            ("historical", {"sortOrder": "sideways"}),
            ("dividends", {"sortBy": "arbitrary"}),
            ("fii-historical", {"range": "1y"}),
            ("fii-dividends", {"sortBy": 1}),
            ("macro", {"limit": 0}),
            ("macro", {"limit": "5"}),
            ("macro", {"limit": True}),
            ("macro", {"startDate": None}),
        )
        for operation, parameters in cases:
            with self.subTest(operation=operation, parameters=parameters):
                with patch.object(_module, "urlopen") as request:
                    with self.assertRaises(BrapiError):
                        fetch_brapi_data(operation, ["TEST"], parameters=parameters)
                    request.assert_not_called()

    def test_public_demo_quote_works_without_token(self) -> None:
        with patch.dict("os.environ", {"BRAPI_TOKEN": ""}):
            with patch.object(_module, "urlopen", return_value=response({})) as request:
                fetch_brapi_data("quote", ["PETR4"])
        headers = {
            name.lower(): value
            for name, value in request.call_args.args[0].header_items()
        }
        self.assertNotIn("authorization", headers)

    def test_rejects_unsupported_operation_before_request(self) -> None:
        for operation in (
            "balance-sheet",
            "../stocks/quote",
            "https://example.com",
            "",
        ):
            with self.subTest(operation=operation):
                with patch.object(_module, "urlopen") as request:
                    with self.assertRaises((ValueError, BrapiError)):
                        fetch_brapi_data(operation, ["PETR4"])
                    request.assert_not_called()

    def test_rejects_unknown_and_authentication_parameters_before_request(self) -> None:
        for key in ("token", "Authorization", "api_key", "unknownParameter"):
            with self.subTest(key=key):
                with patch.object(_module, "urlopen") as request:
                    with self.assertRaises((ValueError, BrapiError)):
                        fetch_brapi_data(
                            "quote", ["PETR4"], parameters={key: "injected"}
                        )
                    request.assert_not_called()

    def test_rejects_empty_symbols_before_request(self) -> None:
        for symbols in ([], ["", "   "]):
            with self.subTest(symbols=symbols):
                with patch.object(_module, "urlopen") as request:
                    with self.assertRaises((ValueError, BrapiError)):
                        fetch_brapi_data("quote", symbols)
                    request.assert_not_called()

    def test_limited_operations_reject_more_than_twenty_symbols(self) -> None:
        for operation, symbols in (
            ("fii-indicators", [f"FUND{i}11" for i in range(21)]),
            ("fii-historical", [f"FUND{i}11" for i in range(21)]),
            ("fii-dividends", [f"FUND{i}11" for i in range(21)]),
            ("macro", [f"indicator{i}" for i in range(21)]),
            ("macro-latest", [f"indicator{i}" for i in range(21)]),
            ("currency-historical", [f"CUR{i}-BRL" for i in range(21)]),
        ):
            with self.subTest(operation=operation):
                with patch.object(_module, "urlopen") as request:
                    with self.assertRaises((ValueError, BrapiError)):
                        fetch_brapi_data(operation, symbols)
                    request.assert_not_called()

    def test_non_retryable_http_errors_preserve_status_and_have_actionable_message(
        self,
    ) -> None:
        for status in (401, 403, 404):
            with self.subTest(status=status):
                with patch.object(
                    _module, "urlopen", side_effect=http_error(status)
                ) as request:
                    with patch.object(_module.time, "sleep") as sleep:
                        with self.assertRaises(BrapiError) as raised:
                            fetch_brapi_data("quote", ["PETR4"])
                self.assertEqual(raised.exception.status_code, status)
                self.assertIn(f"HTTP {status}", str(raised.exception))
                if status == 401:
                    self.assertIn("https://brapi.dev/dashboard", str(raised.exception))
                if status == 403:
                    self.assertIn("https://brapi.dev/pricing", str(raised.exception))
                self.assertNotIn("test-secret-token", str(raised.exception))
                request.assert_called_once()
                sleep.assert_not_called()

    def test_rate_limit_honors_retry_after_then_returns_result(self) -> None:
        with patch.object(
            _module,
            "urlopen",
            side_effect=[http_error(429, "3"), response({"ok": True})],
        ) as request:
            with patch.object(_module.time, "sleep") as sleep:
                result = fetch_brapi_data("quote", ["PETR4"])
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_rate_limit_exhausts_two_retries_with_default_backoff(self) -> None:
        failures = [http_error(429), http_error(429), http_error(429)]
        with patch.object(_module, "urlopen", side_effect=failures) as request:
            with patch.object(_module.time, "sleep") as sleep:
                with self.assertRaises(BrapiError) as raised:
                    fetch_brapi_data("quote", ["PETR4"])
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertEqual(raised.exception.status_code, 429)

    def test_long_retry_after_returns_hint_without_waiting_or_retrying(self) -> None:
        with patch.object(
            _module, "urlopen", side_effect=http_error(429, "120")
        ) as request:
            with patch.object(_module.time, "sleep") as sleep:
                with self.assertRaises(BrapiError) as raised:
                    fetch_brapi_data("quote", ["PETR4"])
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after, 120)
        self.assertIn("120", str(raised.exception))
        request.assert_called_once()
        sleep.assert_not_called()

    def test_http_date_retry_after_preserves_long_delay_without_waiting(self) -> None:
        error = http_error(429, "Thu, 01 Jan 2099 00:00:00 GMT")
        with patch.object(_module, "urlopen", side_effect=error) as request:
            with patch.object(_module.time, "sleep") as sleep:
                with self.assertRaises(BrapiError) as raised:
                    fetch_brapi_data("quote", ["PETR4"])
        self.assertEqual(raised.exception.status_code, 429)
        self.assertIsNotNone(raised.exception.retry_after)
        self.assertGreater(raised.exception.retry_after, 60)
        request.assert_called_once()
        sleep.assert_not_called()

    def test_invalid_json_and_non_object_payloads_raise_domain_error(self) -> None:
        for body in (b"not-json", b"null", b"[]", b"42", b""):
            with self.subTest(body=body):
                with patch.object(
                    _module, "urlopen", return_value=io.BytesIO(body)
                ) as request:
                    with self.assertRaises(BrapiError):
                        fetch_brapi_data("quote", ["PETR4"])
                request.assert_called_once()

    def test_transport_failures_are_sanitized_domain_errors(self) -> None:
        for error in (URLError("test-secret-token"), TimeoutError("test-secret-token")):
            with self.subTest(error=type(error).__name__):
                with patch.object(_module, "urlopen", side_effect=error):
                    with self.assertRaises(BrapiError) as raised:
                        fetch_brapi_data("quote", ["PETR4"])
                self.assertIsNone(raised.exception.status_code)
                self.assertNotIn("test-secret-token", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
