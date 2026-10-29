from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from rikdom import market_series
from rikdom.plugin_engine import pipeline
from rikdom.plugin_engine.errors import PluginEngineError, PluginManifestError


STAMP = '2026-01-02T00:00:00Z'
DOCUMENT = {
    'contract_version': '1.0',
    'series': [{
        'id': 'br-price', 'kind': 'price',
        'instrument': {'namespace': 'BVMF', 'id': 'SYNTH3', 'currency': 'BRL'},
        'currency': 'BRL', 'adjustment': 'unadjusted',
        'coverage': {'start': STAMP, 'end': '2026-01-10T00:00:00Z'},
        'license': {'name': 'CC0-1.0 synthetic', 'uri': 'https://creativecommons.org/publicdomain/zero/1.0/'},
        'observations': [
            {'id': 'original', 'effective_at': STAMP, 'retrieved_at': STAMP,
             'source': 'manual synthetic fixture', 'value': 10, 'currency': 'BRL', 'supersedes': None},
            {'id': 'revision', 'effective_at': STAMP, 'retrieved_at': '2026-01-04T00:00:00Z',
             'source': 'manual synthetic correction', 'value': 12, 'currency': 'BRL', 'supersedes': 'original'},
        ],
    }],
}


def request(path: str = 'ignored') -> dict:
    return {'contract_version': '1.0', 'source': {'path': path}, 'lookups': [
        {'series_id': 'br-price', 'as_of': STAMP, 'max_age_seconds': 0},
    ]}


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def install(self, body: str, api_version: str = '1.2') -> None:
        directory = self.root / 'probe'
        directory.mkdir(exist_ok=True)
        (directory / 'plugin.json').write_text(json.dumps({
            'name': 'probe', 'version': '0.1.0', 'api_version': api_version,
            'plugin_types': ['enrichment'], 'module': 'plugin', 'class_name': 'Plugin',
        }))
        (directory / 'plugin.py').write_text(
            'from rikdom.plugin_engine.hookspecs import hookimpl\n'
            f'DOCUMENT = {DOCUMENT!r}\n'
            'class Plugin:\n    @hookimpl\n    def enrichment(self, ctx, request):\n'
            + ''.join(f'        {line}\n' for line in body.splitlines())
        )

    def run_pipeline(self, req=None):
        run = getattr(pipeline, 'run_enrichment_pipeline', None)
        self.assertTrue(callable(run), 'normalized enrichment pipeline is not implemented')
        return run('probe', str(self.root), request() if req is None else req)

    def test_validated_series_and_host_derived_revision_lookup_are_detached(self):
        self.install("request['source']['path'] = 'mutated'\nrequest['lookups'][0]['series_id'] = 'forged'\nreturn {'contract_version': '1.0', 'market_series': DOCUMENT}")
        req = request()
        result = self.run_pipeline(req)
        self.assertEqual(req['source']['path'], 'ignored')
        self.assertEqual(result['plugin'], {'name': 'probe', 'version': '0.1.0', 'api_version': '1.2'})
        quote = result['lookups'][0]
        self.assertEqual((quote['status'], quote['observation']['value']), ('available', 12))
        self.assertEqual(quote['superseded'][0]['value'], 10)
        self.assertEqual(quote['series']['license']['name'], 'CC0-1.0 synthetic')
        result['market_series']['series'][0]['observations'][0]['value'] = 999
        self.assertEqual(quote['superseded'][0]['value'], 10)
        self.assertEqual(self.run_pipeline()['market_series']['series'][0]['observations'][0]['value'], 10)

    def test_lookup_missing_stale_future_and_revision_cutoff(self):
        self.install("return {'contract_version': '1.0', 'market_series': DOCUMENT}")
        req = request()
        req['lookups'] = [
            {'series_id': 'br-price', 'as_of': STAMP, 'max_age_seconds': 0, 'retrieved_before': STAMP},
            {'series_id': 'br-price', 'as_of': '2026-01-05T00:00:00Z', 'max_age_seconds': 1},
            {'series_id': 'unknown', 'as_of': STAMP, 'max_age_seconds': 0},
            {'series_id': 'br-price', 'as_of': STAMP, 'max_age_seconds': 0, 'retrieved_before': '2026-01-01T00:00:00Z'},
        ]
        rows = self.run_pipeline(req)['lookups']
        self.assertEqual([row['status'] for row in rows], ['available', 'stale', 'missing', 'missing'])
        self.assertEqual(rows[0]['observation']['value'], 10)
        self.assertEqual(rows[1]['age_seconds'], 259200)
        self.assertEqual(rows[3]['reason'], 'no_eligible_observation')
        self.assertEqual(self.run_pipeline(req), self.run_pipeline(req))

    def test_rejects_malformed_responses(self):
        bodies = [
            "return None", "return {'contract_version': '2.0', 'market_series': DOCUMENT}",
            "return {'contract_version': '1.0', 'market_series': DOCUMENT, 'extra': True}",
            "DOCUMENT['series'][0]['observations'][0]['value'] = float('nan')\nreturn {'contract_version': '1.0', 'market_series': DOCUMENT}",
            "DOCUMENT['series'][0]['observations'][0]['currency'] = 'USD'\nreturn {'contract_version': '1.0', 'market_series': DOCUMENT}",
            "DOCUMENT['series'][0]['observations'][1]['supersedes'] = 'absent'\nreturn {'contract_version': '1.0', 'market_series': DOCUMENT}",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.install(body)
                with self.assertRaises(PluginEngineError):
                    self.run_pipeline()

    def test_rejects_bad_requests_before_plugin_invocation(self):
        self.install("raise AssertionError('must not invoke invalid request')")
        bad = [dict(request(), contract_version='2.0'), dict(request(), extra=True),
               dict(request(), source=[]), dict(request(), lookups=[{'series_id': 'x'}])]
        for patch in ({'max_age_seconds': True}, {'as_of': '2026-01-02'}, {'extra': 1}):
            req = request()
            req['lookups'][0].update(patch)
            bad.append(req)
        for req in bad:
            with self.subTest(request=req), self.assertRaises(PluginEngineError):
                self.run_pipeline(req)

    def test_old_api_cannot_claim_enrichment(self):
        for version in ('1.0', '1.1'):
            self.install("return {'contract_version': '1.0', 'market_series': DOCUMENT}", version)
            with self.subTest(version=version), self.assertRaises(PluginManifestError):
                self.run_pipeline()

    def test_legacy_manifest_cannot_register_undeclared_enrichment_hook(self):
        self.install("return {'contract_version': '1.0', 'market_series': DOCUMENT}", '1.0')
        path = self.root / 'probe' / 'plugin.json'
        manifest = json.loads(path.read_text())
        manifest['plugin_types'] = ['source/input']
        path.write_text(json.dumps(manifest))
        from rikdom.plugin_engine.loader import plugin_index
        from rikdom.plugin_engine.runtime import load_plugin_instance
        with self.assertRaises(PluginEngineError):
            load_plugin_instance(path.parent, plugin_index(self.root)['probe'])

    def test_version_gate_covers_pluggy_specname_aliases(self):
        self.install("return {'contract_version': '1.0', 'market_series': DOCUMENT}", '1.0')
        path = self.root / 'probe' / 'plugin.json'
        manifest = json.loads(path.read_text())
        manifest['plugin_types'] = ['source/input']
        path.write_text(json.dumps(manifest))
        code = path.parent / 'plugin.py'
        code.write_text(code.read_text().replace('@hookimpl', '@hookimpl(specname="enrichment")')
                        .replace('def enrichment(', 'def augment('))
        from rikdom.plugin_engine.loader import plugin_index
        from rikdom.plugin_engine.runtime import load_plugin_instance
        with self.assertRaises(PluginEngineError):
            load_plugin_instance(path.parent, plugin_index(self.root)['probe'])

    def test_contract_coverage_requires_fixture_for_enrichment_and_alias(self):
        from rikdom.plugin_engine.contract_runner import coverage_report
        for aliased in (False, True):
            with self.subTest(aliased=aliased):
                self.install("return {'contract_version': '1.0', 'market_series': DOCUMENT}")
                if aliased:
                    code = self.root / 'probe' / 'plugin.py'
                    code.write_text(code.read_text().replace('@hookimpl', '@hookimpl(specname="enrichment")')
                                    .replace('def enrichment(', 'def augment('))
                report = coverage_report(self.root, [])[0]
                self.assertIsNone(report.load_error)
                self.assertIn('enrichment', report.declared_hooks - report.covered_hooks)
                self.assertEqual(self.run_pipeline()['lookups'][0]['observation']['value'], 12)

    def test_legacy_untagged_helper_named_enrichment_remains_compatible(self):
        self.install("return 'private helper'", '1.0')
        path = self.root / 'probe' / 'plugin.json'
        manifest = json.loads(path.read_text())
        manifest['plugin_types'] = ['source/input']
        path.write_text(json.dumps(manifest))
        code = path.parent / 'plugin.py'
        code.write_text(code.read_text().replace('    @hookimpl\n', '') +
                        '    @hookimpl\n    def source_input(self, ctx, input_path):\n'
                        '        return {"provider": "legacy"}\n')
        self.assertEqual(pipeline.run_import_pipeline('probe', str(self.root), 'unused'), {'provider': 'legacy'})
        fixture = path.parent / 'fixtures' / 'source'
        fixture.mkdir(parents=True)
        (fixture / 'case.json').write_text(json.dumps({'hook': 'source_input', 'input': 'input.txt'}))
        (fixture / 'input.txt').write_text('unused')
        (fixture / 'expected.json').write_text(json.dumps({'provider': 'legacy'}))
        from rikdom.plugin_engine.contract_runner import coverage_report, discover_fixtures, run_case
        cases = discover_fixtures(self.root)
        result = run_case(cases[0], self.root, self.root / 'out')
        self.assertIsNone(result.error)
        self.assertEqual(result.payload, {'provider': 'legacy'})
        report = coverage_report(self.root, cases)[0]
        self.assertIsNone(report.load_error)
        self.assertEqual(report.declared_hooks, {'source_input'})
        self.assertFalse(report.declared_hooks - report.covered_hooks)

    def test_contract_runner_rejects_invalid_response_through_real_runtime(self):
        self.install("return {'contract_version': '1.0', 'market_series': {}}")
        fixture = self.root / 'probe' / 'fixtures' / 'malformed'
        fixture.mkdir(parents=True)
        (fixture / 'case.json').write_text(json.dumps({'hook': 'enrichment', 'request': request()}))
        (fixture / 'expected_error.json').write_text(json.dumps({'type': 'PluginEngineError'}))
        from rikdom.plugin_engine.contract_runner import discover_fixtures, run_case
        case = discover_fixtures(self.root)[0]
        result = run_case(case, self.root, self.root / 'out')
        self.assertIsInstance(result.error, PluginEngineError)
        self.assertIn('market_series', str(result.error))
        self.assertIsNone(result.payload)

    def test_in_memory_parser_detaches_and_rejects_bad_document(self):
        parse = getattr(market_series, 'parse_market_series', None)
        self.assertTrue(callable(parse), 'in-memory parser is not implemented')
        doc = copy.deepcopy(DOCUMENT)
        store = parse(doc)
        doc['series'][0]['observations'][1]['value'] = 999
        self.assertEqual(store.lookup('br-price', as_of=STAMP, max_age_seconds=0)['observation']['value'], 12)
        with self.assertRaises(ValueError):
            parse(dict(DOCUMENT, contract_version='2.0'))


if __name__ == '__main__':
    unittest.main()
