from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from rikdom.cli import _copy_template_tree
from rikdom.plugin_engine import run_enrichment_pipeline
from rikdom.plugin_engine.contract_runner import discover_fixtures, run_case
from rikdom.plugin_engine.errors import PluginEngineError


ROOT = Path(__file__).resolve().parents[1]


class LocalEnrichmentTests(unittest.TestCase):
    def test_reference_provider_preserves_local_file_and_replays_deterministically(self):
        path = ROOT / 'plugins/local-market-series/fixtures/sample/input.json'
        self.assertTrue(path.exists(), 'local MarketSeries provider fixture missing')
        before = path.read_bytes()
        request = {'contract_version': '1.0', 'source': {'path': str(path)}, 'lookups': [
            {'series_id': 'br-price', 'as_of': '2026-01-02T00:00:00Z', 'max_age_seconds': 0},
        ]}
        first = run_enrichment_pipeline('local-market-series', str(ROOT / 'plugins'), request)
        self.assertEqual(first['lookups'][0]['observation']['value'], 12)
        self.assertEqual(first, run_enrichment_pipeline('local-market-series', str(ROOT / 'plugins'), request))
        self.assertEqual(path.read_bytes(), before)
        for source in ({'url': 'https://example.com/no-network'}, {'path': str(path), 'fallback': True}):
            with self.subTest(source=source), self.assertRaises(PluginEngineError):
                run_enrichment_pipeline('local-market-series', str(ROOT / 'plugins'), dict(request, source=source))

    def test_contract_runner_validates_enrichment_and_replays_three_markets(self):
        cases = [case for case in discover_fixtures(ROOT / 'plugins') if case.plugin_name == 'local-market-series']
        self.assertGreaterEqual(len(cases), 4, 'missing enrichment contract cases')
        for case in cases:
            with self.subTest(case=case.case_name), tempfile.TemporaryDirectory() as tmp:
                result = run_case(case, ROOT / 'plugins', Path(tmp))
                if case.expected_error:
                    self.assertIsNotNone(result.error)
                    self.assertEqual(type(result.error).__name__, case.expected_error['type'])
                else:
                    self.assertIsNone(result.error, str(result.error))
                    self.assertEqual(result.payload, case.expected_payload)
                    again = run_case(case, ROOT / 'plugins', Path(tmp))
                    self.assertEqual(result.raw_normalized, again.raw_normalized)

    def test_generated_enrichment_template_runs_its_test_and_contract_fixture(self):
        resource = files('rikdom._resources').joinpath('template-enrichment')
        self.assertTrue(resource.is_dir(), 'enrichment SDK template missing')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / 'my-enrichment'
            plugin.mkdir()
            _copy_template_tree(resource, plugin, {'plugin_name': 'my-enrichment', 'plugin_description': 'test scaffold'})
            completed = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                                       cwd=plugin, capture_output=True, text=True,
                                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            cases = discover_fixtures(root)
            self.assertEqual(len(cases), 1)
            result = run_case(cases[0], root, root / 'out')
            self.assertIsNone(result.error, str(result.error))
            self.assertEqual(result.payload['lookups'][0]['observation']['value'], 12)
            manifest = json.loads((plugin / 'plugin.json').read_text())
            self.assertEqual(manifest['plugin_types'], ['enrichment'])


if __name__ == '__main__':
    unittest.main()
