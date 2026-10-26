from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from rikdom.fx import ensure_snapshot_fx_lock
from rikdom.storage import append_jsonl, load_jsonl


class FxTests(unittest.TestCase):
    def test_ensure_snapshot_fx_lock_uses_history_and_auto_ingests_missing_rates(
        self,
    ) -> None:
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

            def _fake_fetcher(
                *, base_currency: str, quote_currencies: list[str], as_of_date: str
            ) -> dict[str, float]:
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
            self.assertEqual(lock["sources"], {"USD": "seed", "EUR": "auto_ingest"})
            self.assertEqual(
                lock["rate_dates"], {"USD": "2026-04-20", "EUR": "2026-04-21"}
            )

            rows = load_jsonl(history_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["quote_currency"], "EUR")
            self.assertEqual(rows[-1]["rate_to_base"], 6.2)

    def test_ensure_snapshot_fx_lock_includes_extra_quote_currencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "fx_rates.jsonl"
            append_jsonl(
                history_path,
                {
                    "as_of_date": "2026-04-20",
                    "base_currency": "BRL",
                    "quote_currency": "EUR",
                    "rate_to_base": 6.1,
                    "source": "seed",
                    "ingested_at": "2026-04-20T00:00:00Z",
                },
            )
            portfolio = {
                "settings": {"base_currency": "BRL"},
                "holdings": [],
            }

            lock, warnings = ensure_snapshot_fx_lock(
                portfolio,
                fx_history_path=history_path,
                snapshot_timestamp="2026-04-21T12:00:00Z",
                auto_ingest=False,
                extra_quote_currencies=["eur", "BRL", "not-a-code"],
            )

            self.assertEqual(warnings, [])
            self.assertEqual(lock["rates_to_base"], {"EUR": 6.1})
            self.assertEqual(lock["rate_dates"], {"EUR": "2026-04-20"})
            self.assertEqual(lock["sources"], {"EUR": "seed"})

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

    def test_ensure_snapshot_fx_lock_preserves_partial_auto_ingest_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "fx_rates.jsonl"
            portfolio = {
                "settings": {"base_currency": "BRL"},
                "holdings": [
                    {"id": "h-usd", "market_value": {"amount": 100, "currency": "USD"}},
                    {"id": "h-eur", "market_value": {"amount": 100, "currency": "EUR"}},
                ],
            }

            def _flaky_fetcher(
                *, base_currency: str, quote_currencies: list[str], as_of_date: str
            ) -> dict[str, float]:
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

    def test_acquisition_is_disabled_by_default_even_with_a_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fx_rates.jsonl"
            calls = []

            def fetcher(**kwargs):
                calls.append(kwargs)
                return {"USD": 5.0}

            lock, warnings = ensure_snapshot_fx_lock(
                {"settings": {"base_currency": "BRL"}},
                fx_history_path=path,
                snapshot_timestamp="2026-04-21T12:00:00Z",
                extra_quote_currencies=["USD"],
                fetcher=fetcher,
            )
            self.assertEqual(calls, [])
            self.assertEqual(lock["rates_to_base"], {})
            self.assertEqual(load_jsonl(path), [])
            self.assertTrue(any("Missing FX rate USD->BRL" in w for w in warnings))

    @unittest.mock.patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden"))
    def test_opt_in_without_fetcher_remains_offline(self, _network) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fx_rates.jsonl"
            lock, warnings = ensure_snapshot_fx_lock(
                {"settings": {"base_currency": "BRL"}},
                fx_history_path=path,
                snapshot_timestamp="2026-04-21T12:00:00Z",
                auto_ingest=True,
                extra_quote_currencies=["USD"],
            )
            _network.assert_not_called()
            self.assertEqual(lock["rates_to_base"], {})
            self.assertEqual(load_jsonl(path), [])
            self.assertEqual(warnings, ["Missing FX rate USD->BRL as of 2026-04-21"])

    def test_injected_rates_keep_effective_date_and_provider_through_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fx_rates.jsonl"
            portfolio = {"settings": {"base_currency": "BRL"}}

            def fetcher(**kwargs):
                self.assertEqual(kwargs, {
                    "base_currency": "BRL", "quote_currencies": ["USD"],
                    "as_of_date": "2026-04-19",
                })
                return {"USD": {
                    "rate_to_base": 5.2, "as_of_date": "2026-04-17",
                    "source": "custom-bank",
                }}

            lock, warnings = ensure_snapshot_fx_lock(
                portfolio, fx_history_path=path,
                snapshot_timestamp="2026-04-19T12:00:00Z",
                extra_quote_currencies=["USD"], auto_ingest=True, fetcher=fetcher,
            )
            self.assertEqual(warnings, [])
            self.assertEqual(lock["rates_to_base"], {"USD": 5.2})
            self.assertEqual(lock["rate_dates"], {"USD": "2026-04-17"})
            self.assertEqual(lock["sources"], {"USD": "custom-bank"})
            row = load_jsonl(path)[0]
            self.assertEqual(row["as_of_date"], "2026-04-17")
            self.assertEqual(row["source"], "custom-bank")
            cached, warnings = ensure_snapshot_fx_lock(
                portfolio, fx_history_path=path,
                snapshot_timestamp="2026-04-19T12:00:00Z",
                extra_quote_currencies=["USD"],
            )
            self.assertEqual(cached, lock)
            self.assertEqual(warnings, [])

    def test_legacy_fetcher_never_receives_a_provider_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fx_rates.jsonl"
            lock, warnings = ensure_snapshot_fx_lock(
                {"settings": {"base_currency": "BRL"}},
                fx_history_path=path, snapshot_timestamp="2026-04-21T12:00:00Z",
                extra_quote_currencies=["USD"], auto_ingest=True,
                fetcher=lambda **kwargs: {"USD": 5.2},
            )
            self.assertEqual(warnings, [])
            self.assertEqual(lock["sources"], {"USD": "auto_ingest"})
            self.assertEqual(load_jsonl(path)[0]["source"], "auto_ingest")

    def test_invalid_acquired_rates_do_not_enter_history(self) -> None:
        invalid = [
            {"rate_to_base": 5.2, "as_of_date": "2026-04-22", "source": "bank"},
            {"rate_to_base": 5.2, "as_of_date": "2026-02-30", "source": "bank"},
            {"rate_to_base": 5.2, "source": "bank"},
            {"rate_to_base": True, "as_of_date": "2026-04-20", "source": "bank"},
            {"rate_to_base": float("inf"), "as_of_date": "2026-04-20", "source": "bank"},
            {"rate_to_base": float("nan"), "as_of_date": "2026-04-20", "source": "bank"},
        ]
        for entry in invalid:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as tmp_dir:
                path = Path(tmp_dir) / "fx_rates.jsonl"
                lock, warnings = ensure_snapshot_fx_lock(
                    {"settings": {"base_currency": "BRL"}},
                    fx_history_path=path, snapshot_timestamp="2026-04-21T12:00:00Z",
                    extra_quote_currencies=["USD"], auto_ingest=True,
                    fetcher=lambda **kwargs: {"USD": entry},
                )
                self.assertEqual(lock["rates_to_base"], {})
                self.assertEqual(load_jsonl(path), [])
                self.assertTrue(any("Missing FX rate USD->BRL" in w for w in warnings))

    def test_history_without_source_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fx_rates.jsonl"
            append_jsonl(path, {"base_currency": "BRL", "quote_currency": "USD",
                                "rate_to_base": 5.0, "as_of_date": "2026-04-20"})
            lock, warnings = ensure_snapshot_fx_lock(
                {"settings": {"base_currency": "BRL"}},
                fx_history_path=path, snapshot_timestamp="2026-04-21T12:00:00Z",
                extra_quote_currencies=["USD"],
            )
            self.assertEqual(warnings, [])
            self.assertEqual(lock["sources"], {"USD": "history"})


if __name__ == "__main__":
    unittest.main()
