"""Offline portfolio valuation replay with literal, hand-calculated totals."""
import copy
import importlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

FIRST = '2026-01-02T00:00:00Z'
SECOND = '2026-01-06T00:00:00Z'
LATER = '2026-01-08T00:00:00Z'


def market_document():
    def series(sid, kind, currency, values, **identity):
        return {
            'id': sid, 'kind': kind, 'currency': currency, **identity,
            'adjustment': 'unadjusted' if kind == 'price' else 'not_applicable',
            'coverage': {'start': '2026-01-01T00:00:00Z', 'end': '2027-01-01T00:00:00Z'},
            'license': {'name': 'CC0', 'uri': 'https://example.invalid/cc0'},
            'observations': [
                {'id': f'{sid}-{index}', 'effective_at': when, 'retrieved_at': when,
                 'source': 'hand-calculated synthetic example', 'value': value,
                 'currency': currency, 'supersedes': None}
                for index, (when, value) in enumerate(values)
            ],
        }
    return {'contract_version': '1.0', 'series': [
        series('stock-us', 'price', 'USD', [(FIRST, 10), (SECOND, 12)],
               instrument={'namespace': 'synthetic', 'id': 'US-ONE', 'currency': 'USD'}),
        series('usd-brl', 'fx', 'BRL', [(FIRST, 5), (SECOND, 6)],
               currency_pair={'base': 'USD', 'quote': 'BRL'}),
    ]}


def replay_document():
    return {
        'contract_version': '1.0', 'market_series_file': 'market.json',
        'price_max_age_seconds': 86400, 'fx_max_age_seconds': 86400,
        'retrieved_before': None, 'series_by_currency': {'USD': 'usd-brl'},
        'snapshots': [
            {'as_of': when, 'source': 'reviewed full position statement',
             'positions_complete': True, 'positions': [
                 {'id': 'stock', 'kind': 'security',
                  'instrument': {'namespace': 'synthetic', 'id': 'US-ONE', 'currency': 'USD'},
                  'quantity': quantity, 'price_series_id': 'stock-us'},
                 {'id': 'cash-brl', 'kind': 'cash', 'currency': 'BRL', 'amount': 20},
                 {'id': 'cash-usd', 'kind': 'cash', 'currency': 'USD', 'amount': 3},
             ]}
            for when, quantity in [(FIRST, 2), (SECOND, 3)]
        ],
    }


class HistoricalValuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.path = self.directory / 'replay.json'
        self.market_path = self.directory / 'market.json'
        self.config = replay_document()
        self.market = market_document()

    def replay(self):
        self.path.write_text(json.dumps(self.config), encoding='utf-8')
        self.market_path.write_text(json.dumps(self.market), encoding='utf-8')
        module = importlib.import_module('rikdom.historical_valuation')
        return module.replay_historical_valuations(self.path, base_currency='BRL')

    def test_replays_explicit_quantities_cash_and_directional_fx(self):
        result = self.replay()
        # Opening: 2*10*5 +20 +3*5 =135. Closing: 3*12*6 +20 +3*6 =254.
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([s['totals']['portfolio_value_base'] for s in result['snapshots']], [135, 254])
        self.assertEqual([s['timestamp'] for s in result['snapshots']], [FIRST, SECOND])
        self.assertEqual(result['snapshots'][0]['base_currency'], 'BRL')
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads((Path(__file__).parents[1] / 'schema/snapshot.schema.json').read_text())
        for snapshot in result['snapshots']:
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(snapshot)
        stock = result['valuations'][0]['positions'][0]
        self.assertEqual((stock['native_value'], stock['base_value']), (20, 100))
        self.assertEqual(stock['position'], self.config['snapshots'][0]['positions'][0])
        self.assertEqual(stock['price']['observation']['source'], 'hand-calculated synthetic example')
        self.assertEqual(stock['price']['series']['license']['name'], 'CC0')
        self.assertEqual(stock['fx']['currency_pair'], {'base': 'USD', 'quote': 'BRL'})
        self.assertTrue(result['valuations'][0]['positions'][1]['fx']['identity'])

    def test_one_missing_position_blocks_every_usable_snapshot_but_keeps_all_evidence(self):
        self.config['snapshots'][1]['positions'][0]['price_series_id'] = 'unknown'
        result = self.replay()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['snapshots'], [])
        self.assertEqual(len(result['valuations']), 2)
        self.assertEqual(len(result['valuations'][1]['positions']), 3)
        failed = result['valuations'][1]
        self.assertIsNone(failed['portfolio_value_base'])
        self.assertEqual(failed['positions'][0]['reason'], 'unknown_series')
        self.assertEqual(failed['positions'][1]['base_value'], 20)
        self.assertTrue(result['diagnostics'])

    def test_explicit_empty_portfolio_is_zero_and_missing_position_assertion_is_unavailable(self):
        self.config['snapshots'][0]['positions'] = []
        self.assertEqual(self.replay()['snapshots'][0]['totals']['portfolio_value_base'], 0)
        self.config['snapshots'][0]['positions_complete'] = False
        result = self.replay()
        self.assertEqual(result['snapshots'], [])
        self.assertIsNone(result['valuations'][0]['portfolio_value_base'])
        self.assertIn('positions_not_asserted_complete', result['valuations'][0]['diagnostics'])

    def test_missing_fx_stale_price_stale_fx_and_future_quotes_are_unavailable(self):
        cases = [('missing_fx', 'missing_currency_mapping'), ('stale_price', 'maximum_age_exceeded'),
                 ('stale_fx', 'maximum_age_exceeded'), ('future', 'no_eligible_observation')]
        for case, reason in cases:
            with self.subTest(case=case):
                self.config, self.market = replay_document(), market_document()
                self.config['snapshots'] = self.config['snapshots'][:1]
                if case == 'missing_fx':
                    self.config['series_by_currency'] = {}
                elif case in ('stale_price', 'stale_fx'):
                    self.config['snapshots'][0]['as_of'] = '2026-01-04T00:00:00Z'
                    self.config['price_max_age_seconds'] = 0 if case == 'stale_price' else 864000
                    self.config['fx_max_age_seconds'] = 0 if case == 'stale_fx' else 864000
                else:
                    self.config['snapshots'][0]['as_of'] = '2026-01-01T00:00:00Z'
                result = self.replay()
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['valuations'][0]['positions'][0]['reason'], reason)
                self.assertEqual(result['snapshots'], [])

    def test_wrong_identity_wrong_series_kind_and_adjusted_prices_are_unavailable(self):
        cases = [('id', 'incompatible_instrument'), ('namespace', 'incompatible_instrument'),
                 ('currency', 'incompatible_instrument'), ('kind', 'incompatible_instrument'),
                 ('split_adjusted', 'unsupported_price_adjustment'),
                 ('total_return_adjusted', 'unsupported_price_adjustment')]
        for case, reason in cases:
            with self.subTest(case=case):
                self.config, self.market = replay_document(), market_document()
                position = self.config['snapshots'][0]['positions'][0]
                if case in ('id', 'namespace', 'currency'):
                    position['instrument'][case] = 'EUR' if case == 'currency' else 'different'
                elif case == 'kind':
                    position['price_series_id'] = 'usd-brl'
                else:
                    self.market['series'][0]['adjustment'] = case
                result = self.replay()
                self.assertEqual(result['status'], 'unavailable')
                evidence = result['valuations'][0]['positions'][0]
                self.assertEqual(evidence['reason'], reason)
                self.assertIsNotNone(evidence['price']['observation'])

    def test_reversed_fx_never_inverts(self):
        fx = self.market['series'][1]
        fx['currency_pair'] = {'base': 'BRL', 'quote': 'USD'}
        fx['currency'] = 'USD'
        for observation in fx['observations']:
            observation['currency'] = 'USD'
            observation['value'] = 0.2
        result = self.replay()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['valuations'][0]['positions'][0]['reason'], 'incompatible_currency_pair')

    def test_revision_cutoff_applies_to_prices_and_fx_and_retains_superseded_rows(self):
        for index, value in [(0, 11), (1, 5.5)]:
            original = self.market['series'][index]['observations'][0]
            self.market['series'][index]['observations'].append({
                **original, 'id': f'corrected-{index}', 'value': value,
                'retrieved_at': LATER, 'supersedes': original['id'],
            })
        latest = self.replay()
        # 2*11*5.5 +20 +3*5.5 =157.5
        self.assertEqual(latest['snapshots'][0]['totals']['portfolio_value_base'], 157.5)
        row = latest['valuations'][0]['positions'][0]
        self.assertEqual(row['price']['superseded'][0]['id'], 'stock-us-0')
        self.assertEqual(row['fx']['superseded'][0]['id'], 'usd-brl-0')
        self.config['retrieved_before'] = FIRST
        original = self.replay()
        self.assertEqual(original['valuations'][0]['portfolio_value_base'], 135)
        self.assertEqual(original['snapshots'], [])  # second requested date not yet known
        self.assertEqual(original['valuations'][0]['positions'][0]['price']['retrieved_before'], FIRST)

    def test_same_second_snapshots_sort_chronologically(self):
        original = copy.deepcopy(self.config['snapshots'][0])
        fractional = copy.deepcopy(original)
        fractional['as_of'] = '2026-01-02T00:00:00.5Z'
        fractional['positions'][0]['quantity'] = 4
        self.config['snapshots'] = [fractional, original]
        result = self.replay()
        self.assertEqual([row['timestamp'] for row in result['snapshots']],
                         [FIRST, '2026-01-02T00:00:00.500000Z'])
        self.assertEqual([row['totals']['portfolio_value_base'] for row in result['snapshots']],
                         [135, 235])

    def test_zero_positions_still_require_quotes_and_do_not_hide_missing_evidence(self):
        position = self.config['snapshots'][0]['positions'][0]
        position['quantity'] = 0
        position['price_series_id'] = 'unknown'
        self.assertEqual(self.replay()['status'], 'unavailable')

    def test_repeat_is_deterministic_detached_and_never_mutates_files(self):
        first = self.replay()
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        replay = importlib.import_module('rikdom.historical_valuation').replay_historical_valuations
        self.assertEqual(first, replay(self.path, base_currency='BRL'))
        first['valuations'][0]['positions'][0]['price']['observation']['value'] = 999
        self.assertEqual(replay(self.path, base_currency='BRL')['snapshots'][0]['totals']['portfolio_value_base'], 135)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_strict_config_and_position_validation(self):
        cases = []
        for key, value in [('contract_version', 1), ('extra', True), ('snapshots', []),
                           ('price_max_age_seconds', True), ('fx_max_age_seconds', -1),
                           ('retrieved_before', '2026-01-02'), ('market_series_file', ' ')]:
            config = replay_document()
            config[key] = value
            cases.append(config)
        for change in [{'quantity': -1}, {'quantity': True}, {'quantity': '2'},
                       {'extra': True}, {'instrument': {'namespace': 'x', 'id': 'y'}}]:
            config = replay_document()
            config['snapshots'][0]['positions'][0].update(change)
            cases.append(config)
        for field in ['source', 'positions', 'positions_complete']:
            config = replay_document()
            del config['snapshots'][0][field]
            cases.append(config)
        for field, value in [('positions_complete', 1), ('source', ''), ('as_of', '2026-01-02'),
                             ('positions', None)]:
            config = replay_document()
            config['snapshots'][0][field] = value
            cases.append(config)
        for field, value in [('amount', -1), ('amount', False), ('currency', 'usd')]:
            config = replay_document()
            config['snapshots'][0]['positions'][1][field] = value
            cases.append(config)
        for config in cases:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.config = config
                self.replay()

    def test_duplicate_snapshot_times_and_position_ids_are_rejected(self):
        self.config['snapshots'][1]['as_of'] = '2026-01-02T00:00:00+00:00'
        with self.assertRaises(ValueError):
            self.replay()
        self.config = replay_document()
        self.config['snapshots'][0]['positions'].append(copy.deepcopy(self.config['snapshots'][0]['positions'][0]))
        with self.assertRaises(ValueError):
            self.replay()

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        self.replay()
        replay = importlib.import_module('rikdom.historical_valuation').replay_historical_valuations
        texts = [json.dumps(self.config).replace('"contract_version": "1.0"',
                   '"contract_version":"1.0","contract_version":"1.0"'),
                 json.dumps(self.config).replace('"quantity": 2', '"quantity": NaN')]
        for value in texts:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.path.write_text(value, encoding='utf-8')
                replay(self.path, base_currency='BRL')

    def test_overflow_cannot_publish_nonfinite_valuations(self):
        for scope in ['native', 'base', 'portfolio']:
            with self.subTest(scope=scope):
                self.config, self.market = replay_document(), market_document()
                positions = self.config['snapshots'][0]['positions']
                if scope == 'native':
                    positions[0]['quantity'] = 1e308
                    self.market['series'][0]['observations'][0]['value'] = 1e308
                elif scope == 'base':
                    positions[2]['amount'] = 1e308
                else:
                    positions[:] = [
                        {'id': 'cash-one', 'kind': 'cash', 'currency': 'BRL', 'amount': 1e308},
                        {'id': 'cash-two', 'kind': 'cash', 'currency': 'BRL', 'amount': 1e308},
                    ]
                result = self.replay()
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(result['valuations'][0]['portfolio_value_base'])
                self.assertEqual(result['snapshots'], [])
                json.dumps(result, allow_nan=False)
