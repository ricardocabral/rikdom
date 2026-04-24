from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from rikdom.fx import ensure_snapshot_fx_lock, fetch_daily_fx_rates_from_frankfurter
from rikdom.storage import append_jsonl, load_jsonl


class FxTests(unittest.TestCase):
    def test_ensure_snapshot_fx_lock_uses_history_and_auto_ingests_missing_rates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "fx_rates.jsonl"
            append_jsonl(
                history_path,
                {
                    "as_of_date": "2026-04-20",
                    "base_currency": "BRL",
                    "quote_currency": "USD",
                    "rate_to_base": 5.3,
                    "source": "seed",
                    "ingested_at": "2026-04-20T00:00:00Z",
                },
            )

            portfolio = {
                "settings": {"base_currency": "BRL"},
                "holdings": [
                    {"id": "h-usd", "market_value": {"amount": 100, "currency": "USD"}},
                    {"id": "h-eur", "market_value": {"amount": 100, "currency": "EUR"}},
                ],
            }

            def _fake_fetcher(*, base_currency: str, quote_currencies: list[str], as_of_date: str) -> dict[str, float]:
                self.assertEqual(base_currency, "BRL")
                self.assertEqual(quote_currencies, ["EUR"])
                self.assertEqual(as_of_date, "2026-04-21")
                return {"EUR": 6.2}

            lock, warnings = ensure_snapshot_fx_lock(
                portfolio,
                fx_history_path=history_path,
                snapshot_timestamp="2026-04-21T12:00:00Z",
                auto_ingest=True,
                fetcher=_fake_fetcher,
            )

            self.assertEqual(warnings, [])
            self.assertEqual(lock["base_currency"], "BRL")
            self.assertEqual(lock["rates_to_base"], {"USD": 5.3, "EUR": 6.2})
            self.assertEqual(lock["sources"], {"USD": "history", "EUR": "auto_ingest"})
            self.assertEqual(lock["rate_dates"], {"USD": "2026-04-20", "EUR": "2026-04-21"})

            rows = load_jsonl(history_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["quote_currency"], "EUR")
            self.assertEqual(rows[-1]["rate_to_base"], 6.2)


    def test_ensure_snapshot_fx_lock_rejects_invalid_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "fx_rates.jsonl"
            portfolio = {
                "settings": {"base_currency": "BRL"},
                "holdings": [
                    {"id": "h-usd", "market_value": {"amount": 100, "currency": "USD"}},
                ],
            }
            for bad in ("", "   ", "not-a-timestamp", "2026-13-40T99:99:99Z"):
                with self.assertRaises(ValueError):
                    ensure_snapshot_fx_lock(
                        portfolio,
                        fx_history_path=history_path,
                        snapshot_timestamp=bad,
                        auto_ingest=False,
                    )

    def test_ensure_snapshot_fx_lock_preserves_partial_auto_ingest_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "fx_rates.jsonl"
            portfolio = {
                "settings": {"base_currency": "BRL"},
                "holdings": [
                    {"id": "h-usd", "market_value": {"amount": 100, "currency": "USD"}},
                    {"id": "h-eur", "market_value": {"amount": 100, "currency": "EUR"}},
                ],
            }

            def _flaky_fetcher(*, base_currency: str, quote_currencies: list[str], as_of_date: str) -> dict[str, float]:
                self.assertEqual(len(quote_currencies), 1)
                currency = quote_currencies[0]
                if currency == "EUR":
                    raise RuntimeError("network blip")
                return {currency: 5.5}

            lock, warnings = ensure_snapshot_fx_lock(
                portfolio,
                fx_history_path=history_path,
                snapshot_timestamp="2026-04-21T12:00:00Z",
                auto_ingest=True,
                fetcher=_flaky_fetcher,
            )

            self.assertEqual(lock["rates_to_base"], {"USD": 5.5})
            self.assertEqual(lock["sources"], {"USD": "auto_ingest"})
            self.assertTrue(any("EUR" in w and "network blip" in w for w in warnings))
            self.assertTrue(any("EUR->BRL" in w for w in warnings))

            rows = load_jsonl(history_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["quote_currency"], "USD")
            self.assertEqual(rows[0]["rate_to_base"], 5.5)


    def test_fetch_daily_fx_rates_from_frankfurter_sets_request_headers(self) -> None:
        import io
        import json as _json

        captured_requests: list = []

        def _fake_urlopen(request, timeout=10):  # noqa: ARG001
            captured_requests.append(request)
            body = _json.dumps({"rates": {"BRL": 5.25}}).encode("utf-8")
            return io.BytesIO(body)

        with patch("rikdom.fx.urlopen", side_effect=_fake_urlopen):
            rates = fetch_daily_fx_rates_from_frankfurter(
                base_currency="BRL",
                quote_currencies=["USD"],
                as_of_date="2026-04-21",
            )

        self.assertEqual(rates, {"USD": 5.25})
        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertIn("frankfurter.app/2026-04-21", request.full_url)
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertIn("rikdom", headers["user-agent"])
        self.assertEqual(headers["accept"], "application/json")


if __name__ == "__main__":
    unittest.main()
