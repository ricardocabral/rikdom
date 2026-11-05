from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from plugins.pluggy import client

ITEM = "207f5bcd-312a-439c-abbe-166b6632c980"
OTHER = "307f5bcd-312a-439c-abbe-166b6632c980"
NOW = "2026-11-05T12:00:00+00:00"


def item(**changes):
    return {"id": ITEM, "status": "UPDATED", "executionStatus": "SUCCESS", **changes}


def page(rows=(), *, number=1, total=None, pages=1):
    return {
        "page": number,
        "total": len(rows) if total is None else total,
        "totalPages": pages,
        "results": list(rows),
    }


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


class PluggyClientTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(
            "os.environ",
            {
                "PLUGGY_CLIENT_ID": "client-secret-id",
                "PLUGGY_CLIENT_SECRET": "client-secret-value",
            },
            clear=True,
        )
        env.start()
        self.addCleanup(env.stop)

    def fetch(self, payloads, **kwargs):
        with patch.object(client, "build_opener") as build:
            build.return_value.open.side_effect = [response(p) for p in payloads]
            result = client.fetch_portfolio([ITEM, ITEM], **kwargs)
            self.requests = [c.args[0] for c in build.return_value.open.call_args_list]
            return result

    def test_auth_snapshot_dedup_and_bank_only(self):
        investment = {"id": "inv-1", "itemId": ITEM}
        result = self.fetch(
            [
                {"apiKey": "key-secret"},
                item(),
                page([{"id": "bank", "itemId": ITEM, "type": "BANK"}]),
                page([investment]),
                page([{"id": "tx-1"}]),
            ]
        )
        self.assertEqual(result["format"], "pluggy-portfolio-v1")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(
            result["items"][0]["investment_transactions"], {"inv-1": [{"id": "tx-1"}]}
        )
        self.assertEqual(
            json.loads(self.requests[0].data),
            {"clientId": "client-secret-id", "clientSecret": "client-secret-value"},
        )
        self.assertEqual(self.requests[1].get_header("X-api-key"), "key-secret")
        self.assertEqual(
            parse_qs(urlsplit(self.requests[2].full_url).query)["type"], ["BANK"]
        )
        self.assertEqual(
            [r.get_method() for r in self.requests],
            ["POST", "GET", "GET", "GET", "GET"],
        )
        self.assertNotIn("key-secret", json.dumps(result))

    def test_pages_fetched_and_identical_duplicates_removed(self):
        inv = {"id": "inv-1", "itemId": ITEM}
        other = {"id": "inv-2", "itemId": ITEM}
        result = self.fetch(
            [
                {"apiKey": "key"},
                item(),
                page([inv], total=2, pages=2),
                page([inv, other], number=2, total=2, pages=2),
            ],
            include_bank_accounts=False,
            include_transactions=False,
        )
        self.assertEqual(result["items"][0]["investments"], [inv, other])
        self.assertEqual(
            parse_qs(urlsplit(self.requests[-1].full_url).query)["page"], ["2"]
        )

    def test_overlapping_pages_cannot_hide_missing_unique_records(self):
        inv = {"id": "inv-1", "itemId": ITEM}
        with self.assertRaisesRegex(client.PluggyError, "count|pagination"):
            self.fetch(
                [
                    {"apiKey": "key"},
                    item(),
                    page([inv], total=2, pages=2),
                    page([inv], number=2, total=2, pages=2),
                ],
                include_bank_accounts=False,
                include_transactions=False,
            )

    def test_invalid_pages_fail(self):
        inv = {"id": "inv-1", "itemId": ITEM}
        for payload in [
            page([inv], total=2),
            {"results": [inv]},
            page([inv], number=2),
            page([inv], number=True),
            page([], total=1),
        ]:
            with self.subTest(payload=payload), self.assertRaises(client.PluggyError):
                self.fetch(
                    [{"apiKey": "key"}, item(), payload],
                    include_bank_accounts=False,
                    include_transactions=False,
                )

    def test_conflicting_duplicate_fails(self):
        with self.assertRaises(client.PluggyError):
            self.fetch(
                [
                    {"apiKey": "key"},
                    item(),
                    page(
                        [
                            {"id": "a", "itemId": ITEM},
                            {"id": "a", "itemId": ITEM, "balance": 2},
                        ]
                    ),
                ],
                include_bank_accounts=False,
                include_transactions=False,
            )

    def test_ownership_and_bank_type_are_checked(self):
        for payloads in [
            [item(id=OTHER)],
            [item(), page([{"id": "a", "itemId": OTHER, "type": "BANK"}])],
            [item(), page([{"id": "a", "itemId": ITEM, "type": "CREDIT"}])],
            [item(), page(), page([{"id": "a", "itemId": OTHER}])],
        ]:
            with self.subTest(payloads=payloads), self.assertRaises(client.PluggyError):
                self.fetch([{"apiKey": "key"}, *payloads])

    def test_incomplete_items_rejected(self):
        for changes in [
            {"status": "LOGIN_ERROR"},
            {"executionStatus": "PARTIAL_SUCCESS"},
            {"status": "UPDATING"},
            {"consentExpiresAt": "2020-01-01T00:00:00Z"},
            {"error": {"message": "secret"}},
            {"hasResourcesPendingAuthorization": True},
            {"userAction": {"type": "LOGIN"}},
            {"statusDetail": {"accounts": {"isUpdated": False}}},
            {
                "statusDetail": {
                    "investments": {
                        "isUpdated": True,
                        "warnings": [{"message": "secret"}],
                    }
                }
            },
            {"statusDetail": {"investmentsTransactions": {"isUpdated": False}}},
        ]:
            with self.subTest(changes=changes), self.assertRaises(client.PluggyError):
                client.validate_item(item(**changes), as_of=NOW)

    def test_unrequested_product_warning_is_allowed(self):
        client.validate_item(
            item(
                statusDetail={
                    "accounts": {"isUpdated": False},
                    "investmentsTransactions": {"isUpdated": False},
                }
            ),
            as_of=NOW,
            include_bank_accounts=False,
            include_transactions=False,
        )

    def test_explicit_env_file_environment_wins_and_does_not_execute(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"PLUGGY_CLIENT_ID": "environment"}, clear=True),
        ):
            path = Path(directory) / "credentials"
            path.write_text(
                '# ignored\nexport PLUGGY_CLIENT_ID=file\nPLUGGY_CLIENT_SECRET="$(touch forbidden)"\nUNRELATED=unused\n'
            )
            self.fetch(
                [{"apiKey": "key"}, item(), page()],
                env_file=path,
                include_bank_accounts=False,
                include_transactions=False,
            )
            self.assertEqual(
                json.loads(self.requests[0].data),
                {"clientId": "environment", "clientSecret": "$(touch forbidden)"},
            )
            self.assertNotIn("PLUGGY_CLIENT_SECRET", client.os.environ)

    def test_missing_credentials_and_bad_ids_make_no_requests(self):
        with patch.object(client, "build_opener") as build:
            for ids in [[], ["bad"], [ITEM, "../auth"]]:
                with self.assertRaises(client.PluggyError):
                    client.fetch_portfolio(ids)
            with (
                patch.dict("os.environ", {}, clear=True),
                self.assertRaises(client.PluggyError),
            ):
                client.fetch_portfolio([ITEM])
            build.assert_not_called()

    def test_invalid_credentials_file_parameter_is_a_safe_error(self):
        with patch.object(client, "build_opener") as build:
            with self.assertRaisesRegex(client.PluggyError, "credentials file"):
                client.fetch_portfolio([ITEM], env_file={"secret": "do-not-print"})
            build.assert_not_called()

    def test_safe_errors_and_bounded_retry(self):
        for error, count in [
            (
                HTTPError("https://secret", "401", "secret", {}, io.BytesIO(b"secret")),
                1,
            ),
            (
                HTTPError("https://secret", "429", "secret", {}, io.BytesIO(b"secret")),
                3,
            ),
            (URLError("secret"), 1),
        ]:
            # HTTPError status is numeric in real urllib responses.
            if isinstance(error, HTTPError):
                error.code = int(error.code)
            with (
                self.subTest(error=type(error)),
                patch.object(client, "build_opener") as build,
                patch.object(client.time, "sleep"),
            ):
                build.return_value.open.side_effect = error
                with self.assertRaises(client.PluggyError) as raised:
                    client.fetch_portfolio([ITEM])
                self.assertNotIn("secret", str(raised.exception))
                self.assertEqual(build.return_value.open.call_count, count)

    def test_redirect_handler_blocks_cross_host(self):
        with self.assertRaises(client.PluggyError):
            client._NoRedirect().redirect_request(
                Request(
                    "https://api.pluggy.ai/items/a", headers={"X-API-KEY": "secret"}
                ),
                None,
                302,
                "Found",
                {},
                "https://evil.example/",
            )


if __name__ == "__main__":
    unittest.main()
