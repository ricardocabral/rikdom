from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rikdom.fx import ensure_snapshot_fx_lock
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


if __name__ == "__main__":
    unittest.main()
