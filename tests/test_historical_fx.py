"""Dated directional FX and local config contract, using synthetic observations."""
import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom import historical_fx
from rikdom.market_series import load_market_series

FIRST = '2026-01-02T00:00:00Z'
SECOND = '2026-01-06T00:00:00Z'


def fx_document():
    return {'contract_version': '1.0', 'series': [{
        'id': 'usd-brl', 'kind': 'fx', 'currency': 'BRL',
        'currency_pair': {'base': 'USD', 'quote': 'BRL'},
        'adjustment': 'not_applicable',
        'coverage': {'start': '2026-01-01T00:00:00Z', 'end': '2027-01-01T00:00:00Z'},
        'license': {'name': 'CC0', 'uri': 'https://example.invalid/license'},
        'observations': [
            {'id': 'first', 'effective_at': FIRST, 'retrieved_at': FIRST,
             'source': 'synthetic', 'value': 5, 'currency': 'BRL', 'supersedes': None},
            {'id': 'second', 'effective_at': SECOND, 'retrieved_at': SECOND,
             'source': 'synthetic', 'value': 6, 'currency': 'BRL', 'supersedes': None},
        ],
    }]}


class HistoricalFxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'series.json'
        self.path.write_text(json.dumps(fx_document()))
        self.series = load_market_series(self.path)

    def resolver(self, **changes):
        return historical_fx.HistoricalFx(self.series, **{
            'base_currency': 'BRL', 'series_by_currency': {'USD': 'usd-brl'},
            'max_age_seconds': 86400, **changes})

    def test_resolves_different_dates_and_retains_provenance(self):
        fx = self.resolver()
        first = fx.resolve('USD', datetime.fromisoformat(FIRST))
        second = fx.resolve('USD', datetime.fromisoformat(SECOND))
        self.assertEqual((first.rate, second.rate), (5, 6))
        self.assertEqual(first.status, 'available')
        self.assertEqual(first.evidence['observation']['source'], 'synthetic')
        self.assertEqual(first.evidence['series']['license']['name'], 'CC0')
        self.assertEqual(first.evidence['as_of'], FIRST)
        self.assertEqual(first.evidence['currency_pair'], {'base': 'USD', 'quote': 'BRL'})

    def test_native_identity_without_mapping(self):
        result = self.resolver(series_by_currency={}).resolve('BRL', datetime.fromisoformat(FIRST))
        self.assertEqual((result.status, result.rate), ('available', 1))

    def test_missing_stale_unknown_and_incompatible_pairs_never_resolve(self):
        for currency, changes, when, reason in [
            ('EUR', {}, FIRST, 'missing_currency_mapping'),
            ('USD', {}, '2026-01-04T00:00:00Z', 'maximum_age_exceeded'),
            ('USD', {'series_by_currency': {'USD': 'unknown'}}, FIRST, 'unknown_series'),
            ('EUR', {'series_by_currency': {'EUR': 'usd-brl'}}, FIRST, 'incompatible_currency_pair'),
        ]:
            with self.subTest(reason=reason):
                result = self.resolver(**changes).resolve(currency, datetime.fromisoformat(when))
                self.assertIsNone(result.rate)
                self.assertEqual(result.reason, reason)

    def test_revision_cutoff_changes_rate_and_keeps_revision_evidence(self):
        document = fx_document()
        document['series'][0]['observations'].append({
            **document['series'][0]['observations'][0], 'id': 'corrected', 'value': 5.5,
            'retrieved_at': '2026-01-03T00:00:00Z', 'supersedes': 'first'})
        self.path.write_text(json.dumps(document))
        self.series = load_market_series(self.path)
        latest = self.resolver().resolve('USD', datetime.fromisoformat(FIRST))
        original = self.resolver(retrieved_before=FIRST).resolve('USD', datetime.fromisoformat(FIRST))
        self.assertEqual((latest.rate, original.rate), (5.5, 5))
        self.assertEqual(latest.evidence['superseded'][0]['id'], 'first')

    def test_constructor_rejects_invalid_configuration_eagerly(self):
        for changes in [
            {'base_currency': 'brl'}, {'series_by_currency': []},
            {'series_by_currency': {'usd': 'usd-brl'}},
            {'series_by_currency': {'USD': ''}}, {'series_by_currency': {'USD': 2}},
            {'max_age_seconds': True}, {'max_age_seconds': float('inf')},
            {'max_age_seconds': -1}, {'retrieved_before': '2026-01-01'},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.resolver(**changes)

    def test_rejects_naive_request_and_invalid_currency(self):
        with self.assertRaises(ValueError):
            self.resolver().resolve('USD', datetime(2026, 1, 2))
        with self.assertRaises(ValueError):
            self.resolver().resolve('usd', datetime.fromisoformat(FIRST))

    def config(self):
        return {'contract_version': '1.0', 'market_series_file': 'series.json',
                'series_by_currency': {'USD': 'usd-brl'}, 'max_age_seconds': 86400,
                'retrieved_before': None}

    def test_loads_relative_local_config(self):
        config = Path(self.tmp.name) / 'fx.json'
        config.write_text(json.dumps(self.config()))
        result = historical_fx.load_historical_fx(config, base_currency='BRL')
        self.assertEqual(result.resolve('USD', datetime.fromisoformat(FIRST)).rate, 5)

    def test_rejects_non_strict_config(self):
        config = Path(self.tmp.name) / 'fx.json'
        cases = [dict(self.config(), extra=True), dict(self.config(), contract_version=1),
                 dict(self.config(), market_series_file=' ')]
        missing = self.config()
        del missing['retrieved_before']
        cases.append(missing)
        texts = [json.dumps(row) for row in cases]
        texts += ['{"contract_version":"1.0","contract_version":"1.0"}',
                  json.dumps(dict(self.config(), max_age_seconds=float('nan')))]
        for value in texts:
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.write_text(value)
                historical_fx.load_historical_fx(config, base_currency='BRL')
