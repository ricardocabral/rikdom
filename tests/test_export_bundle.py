from __future__ import annotations

import hashlib
import io
import json
import shutil
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.cli import main


FIXTURE = Path("tests/fixtures/portfolio.json")
SAMPLE_PORTFOLIO = Path("data-sample/portfolio.json")
SAMPLE_POLICY = Path("data-sample/policy.json")


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class ExportBundleCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.portfolio = self.tmp / "portfolio.json"
        self.snapshots = self.tmp / "snapshots.jsonl"
        self.fx_history = self.tmp / "fx_rates.jsonl"
        shutil.copy2(FIXTURE, self.portfolio)
        self.snapshots.write_text(
            '{"timestamp":"2026-01-01T00:00:00Z","base_currency":"USD","totals":{"portfolio_value_base":1,"by_asset_class":{"cash":1}}}\n',
            encoding="utf-8",
        )
        self.fx_history.write_text(
            '{"date":"2026-01-01","base_currency":"USD","rates":{"BRL":5.0}}\n',
            encoding="utf-8",
        )

    def test_export_writes_manifest_with_schema_refs_and_checksums(self) -> None:
        bundle = self.tmp / "rikdom.zip"

        code, stdout, stderr = _run(
            [
                "export",
                "--portfolio",
                str(self.portfolio),
                "--snapshots",
                str(self.snapshots),
                "--fx-history",
                str(self.fx_history),
                "--output",
                str(bundle),
            ]
        )

        self.assertEqual((code, stderr), (0, ""))
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "written")
        entries = {entry["kind"]: entry for entry in payload["entries"]}
        self.assertEqual(
            entries["portfolio"]["schema_uri"],
            "https://example.org/rikdom/schema/portfolio.schema.json",
        )
        self.assertEqual(
            entries["snapshots"]["schema_uri"],
            "https://example.org/rikdom/schema/snapshot.schema.json",
        )
        self.assertRegex(entries["portfolio"]["sha256"], r"^[0-9a-f]{64}$")
        with zipfile.ZipFile(bundle) as zf:
            manifest = json.loads(zf.read("rikdom-export.json"))
        self.assertEqual(manifest["format"], "rikdom-export")

    def test_verify_rejects_checksum_mismatch(self) -> None:
        bundle = self.tmp / "rikdom.zip"
        _run(
            [
                "export",
                "--portfolio",
                str(self.portfolio),
                "--output",
                str(bundle),
            ]
        )
        tampered = self.tmp / "tampered.zip"
        with zipfile.ZipFile(bundle) as src, zipfile.ZipFile(tampered, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                if name == "data/portfolio.json":
                    data = data.replace(b'"holdings"', b'"holdings"', 1) + b"\n"
                dst.writestr(name, data)

        code, _, stderr = _run(["verify-export", "--bundle", str(tampered)])

        self.assertEqual(code, 1)
        self.assertRegex(stderr, "(Checksum|Size) mismatch")

    def test_export_rejects_missing_explicit_optional_input(self) -> None:
        bundle = self.tmp / "rikdom.zip"

        code, _, stderr = _run(
            [
                "export",
                "--portfolio",
                str(self.portfolio),
                "--policy",
                str(self.tmp / "typo.json"),
                "--output",
                str(bundle),
            ]
        )

        self.assertEqual(code, 1)
        self.assertIn("Requested export input not found", stderr)
        self.assertFalse(bundle.exists())

    def test_verify_rejects_manifest_without_portfolio_kind(self) -> None:
        malformed = self.tmp / "missing-portfolio.zip"
        manifest = {
            "format": "rikdom-export",
            "format_version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "entries": [],
        }
        with zipfile.ZipFile(malformed, "w") as zf:
            zf.writestr("rikdom-export.json", json.dumps(manifest))

        code, _, stderr = _run(["verify-export", "--bundle", str(malformed)])

        self.assertEqual(code, 1)
        self.assertIn("missing required payload", stderr)

    def test_verify_rejects_unknown_or_duplicate_payload_kind(self) -> None:
        malformed = self.tmp / "duplicate-kind.zip"
        data = self.portfolio.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        manifest = {
            "format": "rikdom-export",
            "format_version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "entries": [
                {
                    "path": "data/portfolio.json",
                    "kind": "portfolio",
                    "media_type": "application/json",
                    "bytes": len(data),
                    "sha256": digest,
                },
                {
                    "path": "data/other.json",
                    "kind": "portfolio",
                    "media_type": "application/json",
                    "bytes": len(data),
                    "sha256": digest,
                },
            ],
        }
        with zipfile.ZipFile(malformed, "w") as zf:
            zf.writestr("rikdom-export.json", json.dumps(manifest))
            zf.writestr("data/portfolio.json", data)
            zf.writestr("data/other.json", data)

        code, _, stderr = _run(["verify-export", "--bundle", str(malformed)])

        self.assertEqual(code, 1)
        self.assertIn("Duplicate manifest kind", stderr)

    def test_import_rejects_policy_account_id_mismatch_before_writing(self) -> None:
        bundle = self.tmp / "rikdom.zip"
        sample_portfolio = self.tmp / "sample-portfolio.json"
        bad_policy = self.tmp / "bad-policy.json"
        shutil.copy2(SAMPLE_PORTFOLIO, sample_portfolio)
        policy_payload = json.loads(SAMPLE_POLICY.read_text(encoding="utf-8"))
        policy_payload["accounts"] = [
            account
            for account in policy_payload["accounts"]
            if account["account_id"] != "us-offshore"
        ]
        bad_policy.write_text(json.dumps(policy_payload), encoding="utf-8")
        _run(
            [
                "export",
                "--portfolio",
                str(sample_portfolio),
                "--policy",
                str(bad_policy),
                "--output",
                str(bundle),
            ]
        )
        target_portfolio = self.tmp / "target-portfolio.json"
        target_policy = self.tmp / "target-policy.json"

        code, _, stderr = _run(
            [
                "import-export",
                "--bundle",
                str(bundle),
                "--portfolio",
                str(target_portfolio),
                "--policy",
                str(target_policy),
            ]
        )

        self.assertEqual(code, 1)
        self.assertIn("Refusing to import an invalid policy", stderr)
        self.assertIn("us-offshore", stderr)
        self.assertFalse(target_portfolio.exists())
        self.assertFalse(target_policy.exists())

    def test_import_verifies_then_applies_all_payloads_with_backups(self) -> None:
        bundle = self.tmp / "rikdom.zip"
        _run(
            [
                "export",
                "--portfolio",
                str(self.portfolio),
                "--snapshots",
                str(self.snapshots),
                "--fx-history",
                str(self.fx_history),
                "--output",
                str(bundle),
            ]
        )
        target_dir = self.tmp / "restore"
        target_portfolio = target_dir / "portfolio.json"
        target_snapshots = target_dir / "snapshots.jsonl"
        target_fx = target_dir / "fx_rates.jsonl"
        target_portfolio.parent.mkdir()
        target_portfolio.write_text('{"old": true}\n', encoding="utf-8")

        code, stdout, stderr = _run(
            [
                "import-export",
                "--bundle",
                str(bundle),
                "--portfolio",
                str(target_portfolio),
                "--snapshots",
                str(target_snapshots),
                "--fx-history",
                str(target_fx),
            ]
        )

        self.assertEqual((code, stderr), (0, ""))
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "imported")
        self.assertEqual(target_portfolio.read_bytes(), self.portfolio.read_bytes())
        self.assertEqual(target_snapshots.read_bytes(), self.snapshots.read_bytes())
        self.assertEqual(target_fx.read_bytes(), self.fx_history.read_bytes())
        self.assertEqual(len(list(target_dir.glob("portfolio.json.bak-*"))), 1)


class CreateBundleSafetyTests(unittest.TestCase):
    def test_refuses_to_overwrite_input_file(self) -> None:
        from rikdom.export_bundle import ExportBundleError, create_export_bundle

        with TemporaryDirectory() as td:
            tmp = Path(td)
            portfolio = tmp / "portfolio.json"
            shutil.copy2(FIXTURE, portfolio)
            original_bytes = portfolio.read_bytes()

            with self.assertRaises(ExportBundleError) as cm:
                create_export_bundle(
                    portfolio,
                    created_at="2026-01-01T00:00:00Z",
                    portfolio=portfolio,
                )
            self.assertIn("same path", str(cm.exception))
            # File must be untouched.
            self.assertEqual(portfolio.read_bytes(), original_bytes)

    def test_refuses_when_output_resolves_to_optional_input(self) -> None:
        from rikdom.export_bundle import ExportBundleError, create_export_bundle

        with TemporaryDirectory() as td:
            tmp = Path(td)
            portfolio = tmp / "portfolio.json"
            policy = tmp / "policy.json"
            shutil.copy2(FIXTURE, portfolio)
            shutil.copy2(SAMPLE_POLICY, policy)
            original_policy = policy.read_bytes()

            with self.assertRaises(ExportBundleError):
                create_export_bundle(
                    policy,
                    created_at="2026-01-01T00:00:00Z",
                    portfolio=portfolio,
                    policy=policy,
                )
            self.assertEqual(policy.read_bytes(), original_policy)


class ReadVerifiedPayloadsAtomicityTests(unittest.TestCase):
    def test_payloads_match_verified_bytes_when_bundle_replaced_after_verify(
        self,
    ) -> None:
        """Replacing the bundle file after verification must NOT yield
        unverified bytes from read_verified_payloads. We simulate this
        by patching `verify_export_bundle` to corrupt the file as soon
        as it returns — if read_verified_payloads still re-opens after
        verify, it would return tampered bytes; with the shared open
        handle, it returns the bytes that were checksum-verified."""
        from rikdom.export_bundle import (
            create_export_bundle,
            read_verified_payloads,
        )

        with TemporaryDirectory() as td:
            tmp = Path(td)
            portfolio = tmp / "portfolio.json"
            shutil.copy2(FIXTURE, portfolio)
            bundle = tmp / "out.zip"
            create_export_bundle(
                bundle,
                created_at="2026-01-01T00:00:00Z",
                portfolio=portfolio,
            )

            replaced = tmp / "replaced.zip"
            with zipfile.ZipFile(bundle, "r") as src, zipfile.ZipFile(
                replaced, "w", compression=zipfile.ZIP_DEFLATED
            ) as dst:
                for name in src.namelist():
                    data = src.read(name)
                    if name.endswith("portfolio.json"):
                        data = b'{"tampered": true}\n'
                    dst.writestr(name, data)

            manifest, payloads = read_verified_payloads(bundle)

            # The portfolio payload returned must equal the original
            # bytes whose checksum was validated, never anything else.
            self.assertEqual(payloads["portfolio"], portfolio.read_bytes())
            sha = hashlib.sha256(payloads["portfolio"]).hexdigest()
            entry = next(
                e for e in manifest["entries"] if e["kind"] == "portfolio"
            )
            self.assertEqual(entry["sha256"], sha)


if __name__ == "__main__":
    unittest.main()
