from __future__ import annotations

import unittest

from rikdom.aggregate import AggregateResult
from rikdom.snapshot import snapshot_from_aggregate


class SnapshotFxLockTests(unittest.TestCase):
    def test_snapshot_from_aggregate_persists_fx_lock_metadata(self) -> None:
        result = AggregateResult(
            base_currency="BRL",
            total_value_base=123.45,
            by_asset_class={"stocks": 123.45},
            warnings=[],
            fx_lock={
                "base_currency": "BRL",
                "snapshot_timestamp": "2026-04-21T10:00:00Z",
                "rates_to_base": {"USD": 5.2},
                "rate_dates": {"USD": "2026-04-21"},
                "sources": {"USD": "history"},
            },
        )

        snapshot = snapshot_from_aggregate(result, timestamp="2026-04-21T10:00:00Z")

        self.assertIn("metadata", snapshot)
        self.assertIn("fx_lock", snapshot["metadata"])
        self.assertEqual(snapshot["metadata"]["fx_lock"]["rates_to_base"]["USD"], 5.2)


if __name__ == "__main__":
    unittest.main()
