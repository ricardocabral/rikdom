from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rikdom.cli import main


def _portfolio() -> dict:
    return {
        "schema_version": "1.3.0",
        "schema_uri": "https://example.org/rikdom/schema/portfolio.schema.json",
        "profile": {
            "portfolio_id": "p",
            "owner_kind": "person",
            "display_name": "P",
        },
        "settings": {"base_currency": "BRL"},
        "asset_type_catalog": [{"id": "stock", "asset_class": "stocks"}],
        "holdings": [
            {
                "id": "h1",
                "asset_type_id": "stock",
                "account_id": "br-taxable-main",
                "label": "A",
                "market_value": {"amount": 100.0, "currency": "BRL"},
            },
        ],
    }


def _policy(account_ids: list[str]) -> dict:
    return {"accounts": [{"account_id": aid} for aid in account_ids]}


class CliValidatePolicyTests(unittest.TestCase):
    def _run(self, *args: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(list(args))
        return rc, buf.getvalue()

    def test_validate_without_policy_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ppath = Path(td) / "portfolio.json"
            ppath.write_text(json.dumps(_portfolio()), encoding="utf-8")
            rc, out = self._run("validate", "--portfolio", str(ppath))
            self.assertEqual(rc, 0, out)
            self.assertIn("valid", out)

    def test_validate_with_policy_passes_when_account_id_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ppath = Path(td) / "portfolio.json"
            polpath = Path(td) / "policy.json"
            ppath.write_text(json.dumps(_portfolio()), encoding="utf-8")
            polpath.write_text(
                json.dumps(_policy(["br-taxable-main"])), encoding="utf-8"
            )
            rc, out = self._run(
                "validate",
                "--portfolio",
                str(ppath),
                "--policy",
                str(polpath),
            )
            self.assertEqual(rc, 0, out)

    def test_validate_with_policy_fails_on_unknown_account_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ppath = Path(td) / "portfolio.json"
            polpath = Path(td) / "policy.json"
            ppath.write_text(json.dumps(_portfolio()), encoding="utf-8")
            polpath.write_text(json.dumps(_policy(["other"])), encoding="utf-8")
            rc, out = self._run(
                "validate",
                "--portfolio",
                str(ppath),
                "--policy",
                str(polpath),
            )
            self.assertEqual(rc, 1)
            self.assertIn("br-taxable-main", out)
            self.assertIn("not declared", out)

    def test_validate_with_policy_warns_when_holding_has_no_account(self) -> None:
        portfolio = _portfolio()
        portfolio["holdings"].append(
            {
                "id": "h2",
                "asset_type_id": "stock",
                "label": "Unassigned",
                "market_value": {"amount": 10.0, "currency": "BRL"},
            }
        )
        with tempfile.TemporaryDirectory() as td:
            ppath = Path(td) / "portfolio.json"
            polpath = Path(td) / "policy.json"
            ppath.write_text(json.dumps(portfolio), encoding="utf-8")
            polpath.write_text(
                json.dumps(_policy(["br-taxable-main"])), encoding="utf-8"
            )
            rc, out = self._run(
                "validate",
                "--portfolio",
                str(ppath),
                "--policy",
                str(polpath),
            )
            self.assertEqual(rc, 0, out)
            self.assertIn("with warnings", out)
            self.assertIn("holdings[1]", out)


if __name__ == "__main__":
    unittest.main()
