"""Reviewed multicurrency FIFO: explicit native cash and independently dated FX."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rikdom.historical_fx import HistoricalFx, load_historical_fx
from rikdom.market_series import load_market_series
from rikdom.performance import compute_performance
from rikdom.profit_attribution import compute_profit_attribution, load_profit_basis

ACQUIRED = '2025-12-01T00:00:00Z'
START = '2026-01-01T00:00:00Z'
SALE = '2026-01-15T00:00:00Z'
END = '2026-02-01T00:00:00Z'
CUTOFF = '2026-02-02T00:00:00Z'


def fixture():
    identity = {'account_id': 'a', 'holding_id': 'h', 'currency': 'USD'}
    cash = {'account_id': 'a', 'currency': 'USD'}
    basis = {
        'contract_version': '2.0', 'scope': 'portfolio', 'base_currency': 'BRL',
        'period_start': START, 'period_end': END, 'method': 'fifo',
        'price_adjustment': 'unadjusted',
        'cost_convention': 'buy_costs_capitalized_sell_costs_deducted',
        'review': {'status': 'reviewed', 'source': 'synthetic',
                   'reviewed_at': CUTOFF, 'retrieved_before': CUTOFF},
        'history': {'status': 'complete', 'from': START, 'through': END, 'missing_periods': []},
        'inventory': {'status': 'complete', 'account_ids': ['a'],
                      'positions': [identity], 'cash': [cash]},
        'opening_cash': [{**cash, 'amount': 50}],
        'closing_cash': [{**cash, 'amount': 110}],
        'opening_lots': [{**identity, 'id': 'old', 'acquired_at': ACQUIRED,
                          'quantity': 10, 'total_cost_native': 100}],
        'opening_positions': [{**identity, 'quantity': 10, 'market_value_native': 120}],
        'closing_positions': [{**identity, 'quantity': 6, 'market_value_native': 90}],
    }
    portfolio = {'schema_version': '2.0.0', 'base_currency': 'BRL', 'activities': [{
        'id': 'sale', 'account_id': 'a', 'holding_id': 'h', 'event_type': 'sell',
        'effective_at': SALE, 'quantity': 4, 'money': {'amount': 60, 'currency': 'USD'}}]}
    return portfolio, basis


class MulticurrencyProfitTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.document = {'contract_version': '1.0', 'series': [{
            'id': 'usd-brl', 'kind': 'fx', 'currency': 'BRL',
            'currency_pair': {'base': 'USD', 'quote': 'BRL'}, 'adjustment': 'not_applicable',
            'coverage': {'start': ACQUIRED, 'end': END},
            'license': {'name': 'CC0', 'uri': 'https://example.invalid/license'},
            'observations': [{'id': str(i), 'effective_at': when, 'retrieved_at': when,
                              'source': 'synthetic', 'value': value, 'currency': 'BRL',
                              'supersedes': None}
                             for i, (when, value) in enumerate([(ACQUIRED, 4), (START, 5), (SALE, 6), (END, 7)])]}]}

    def fx(self, **changes):
        path = Path(self.directory.name) / 'fx.json'
        path.write_text(json.dumps(self.document))
        return HistoricalFx(load_market_series(path), **{
            'base_currency': 'BRL', 'series_by_currency': {'USD': 'usd-brl'},
            'max_age_seconds': 0, 'retrieved_before': CUTOFF, **changes})

    def calculate(self, p, b, opening=850, closing=1400, fx=None):
        fx = fx or self.fx()
        snapshots = [{'timestamp': d, 'base_currency': 'BRL',
                      'totals': {'portfolio_value_base': v}}
                     for d, v in [(START, opening), (END, closing)]]
        perf = compute_performance(snapshots, p['activities'], base_currency='BRL', historical_fx=fx)
        return compute_profit_attribution(p, perf, basis=b, historical_fx=fx)

    def complete(self, result):
        self.assertEqual(result['decomposition']['status'], 'complete', result['diagnostics'])
        return result['decomposition']

    def test_acquisition_sale_bookend_and_cash_fx_are_independent_components(self):
        p, b = fixture()
        originals = copy.deepcopy((p, b))
        d = self.complete(self.calculate(p, b))
        self.assertEqual(d['realized_price_gain_base'], 120)
        self.assertEqual(d['realized_fx_gain_base'], 80)
        self.assertEqual(d['unrealized_price_change_base'], 110)
        self.assertEqual(d['unrealized_fx_change_base'], 80)
        self.assertEqual(d['cash_fx_gain_base'], 160)
        self.assertEqual(d['explained_result_base'], 550)
        self.assertEqual(d['reconciliation_difference_base'], 0)
        self.assertEqual((p, b), originals)
        self.assertTrue(any(row['purpose'] == 'opening_lot' for row in d['fx_evidence']))

    def cash_only(self, opening, closing):
        p, b = fixture()
        p['activities'] = []
        b['opening_lots'] = []
        b['opening_positions'] = []
        b['closing_positions'] = []
        b['inventory']['positions'] = []
        b['inventory']['cash'] = [{'account_id': 'a', 'currency': code} for code in opening]
        b['opening_cash'] = [{'account_id': 'a', 'currency': code, 'amount': amount} for code, amount in opening.items()]
        b['closing_cash'] = [{'account_id': 'a', 'currency': code, 'amount': closing[code]} for code in opening]
        return p, b

    def event(self, aid, kind, amount, code='USD', **extra):
        return {'id': aid, 'event_type': kind, 'account_id': 'a', 'effective_at': SALE,
                'money': {'amount': amount, 'currency': code}, **extra}

    def test_v2_rejects_invalid_rfc3339_offsets_and_date_variants(self):
        for field in ('acquired_at', 'reviewed_at', 'effective_at'):
            p, b = fixture()
            if field == 'acquired_at':
                b['opening_lots'][0][field] = '2025-12-01T00:00:00+00:99'
            elif field == 'reviewed_at':
                b['review'][field] = '2026-02-03T00:00:00+00:99'
            else:
                p['activities'][0][field] = '2026-01-15T00:00:00+00:99'
            with self.subTest(field=field):
                self.assertEqual(self.calculate(p, b)['decomposition']['status'], 'unavailable')

    def test_cross_currency_sale_fee_is_debited_and_deducted_once(self):
        p, b = fixture()
        b['inventory']['cash'].append({'account_id': 'a', 'currency': 'BRL'})
        b['opening_cash'].append({'account_id': 'a', 'currency': 'BRL', 'amount': 20})
        b['closing_cash'].append({'account_id': 'a', 'currency': 'BRL', 'amount': 8})
        p['activities'][0]['fees'] = {'amount': 12, 'currency': 'BRL'}
        d = self.complete(self.calculate(p, b, opening=870, closing=1408))
        self.assertEqual(d['realized_price_gain_base'], 108)
        self.assertEqual(d['realized_fx_gain_base'], 80)
        self.assertEqual(d['standalone_fees_base'], 0)
        self.assertEqual(d['explained_result_base'], 538)

    def test_buy_capitalizes_cross_currency_charges_at_event_fx(self):
        p, b = self.cash_only({'USD': 100, 'BRL': 1000}, {'USD': 39, 'BRL': 988})
        identity = {'account_id': 'a', 'holding_id': 'h', 'currency': 'USD'}
        b['inventory']['positions'] = [identity]
        b['opening_positions'] = [{**identity, 'quantity': 0, 'market_value_native': 0}]
        b['closing_positions'] = [{**identity, 'quantity': 5, 'market_value_native': 75}]
        p['activities'] = [self.event('buy', 'buy', 60, holding_id='h', quantity=5,
                                     fees={'amount': 12, 'currency': 'BRL'},
                                     withholding_tax={'amount': 1, 'currency': 'USD'})]
        d = self.complete(self.calculate(p, b, opening=1500, closing=1786))
        self.assertEqual(d['holdings'][0]['remaining_cost_native'], 63)
        self.assertEqual(d['holdings'][0]['remaining_historical_cost_base'], 378)
        self.assertEqual(d['unrealized_price_change_base'], 84)
        self.assertEqual(d['unrealized_fx_change_base'], 63)
        self.assertEqual(d['cash_fx_gain_base'], 139)

    def test_contribution_gross_income_and_standalone_charges_keep_native_cash(self):
        p, b = self.cash_only({'USD': 50, 'BRL': 20}, {'USD': 68, 'BRL': 15})
        p['activities'] = [self.event('contribution', 'contribution', 10),
                           self.event('income', 'dividend', 10,
                                      metadata={'rikdom_income': {'version': 1, 'amount_basis': 'gross'}},
                                      fees={'amount': 1, 'currency': 'USD'},
                                      withholding_tax={'amount': 2, 'currency': 'BRL'}),
                           self.event('fee', 'fee', 3, 'BRL'), self.event('tax', 'tax_withheld', 1)]
        d = self.complete(self.calculate(p, b, opening=270, closing=491))
        self.assertEqual(d['net_income_base'], 52)
        self.assertEqual(d['standalone_fees_base'], 3)
        self.assertEqual(d['standalone_taxes_base'], 6)
        self.assertEqual(d['cash_fx_gain_base'], 118)
        self.assertEqual(d['explained_result_base'], 161)

    def test_explicit_conversion_spread_and_charges_are_separate_from_cash_fx(self):
        p, b = self.cash_only({'USD': 0, 'BRL': 620}, {'USD': 99, 'BRL': 18})
        p['activities'] = [self.event('fx', 'fx_conversion', 600, 'BRL',
                                     counter_money={'amount': 99, 'currency': 'USD'},
                                     fx_rate=0.165, fees={'amount': 2, 'currency': 'BRL'})]
        d = self.complete(self.calculate(p, b, opening=620, closing=711))
        self.assertEqual(d['fx_conversion_result_base'], -6)
        self.assertEqual(d['cash_fx_gain_base'], 99)
        self.assertEqual(d['standalone_fees_base'], 2)
        self.assertEqual(d['explained_result_base'], 91)

    def test_net_income_keeps_same_currency_embedded_charges_informational(self):
        p, b = self.cash_only({'USD': 50}, {'USD': 60})
        p['activities'] = [self.event('income', 'income', 10,
                                     metadata={'rikdom_income': {'version': 1, 'amount_basis': 'net'}},
                                     fees={'amount': 1, 'currency': 'USD'},
                                     withholding_tax={'amount': 2, 'currency': 'USD'})]
        d = self.complete(self.calculate(p, b, opening=250, closing=420))
        self.assertEqual(d['net_income_base'], 60)
        self.assertEqual(d['cash_fx_gain_base'], 110)
        income = d['activity_evidence'][0]
        self.assertEqual(income['applied_charges_base'], 0)
        self.assertEqual(income['reported_fees'], {'amount': 1, 'currency': 'USD'})
        self.assertEqual(income['reported_taxes'], {'amount': 2, 'currency': 'USD'})
        self.assertEqual(income['cash_movements'], [
            {'currency': 'USD', 'amount_native': 10, 'amount_base': 60}])
        p['activities'][0]['fees']['currency'] = 'BRL'
        self.assertEqual(self.calculate(p, b, opening=250, closing=420)['decomposition']['status'], 'unavailable')

    def test_split_and_reverse_split_preserve_costs_and_proportional_fifo(self):
        for ratio, sale_qty, closing_qty in [(2, 8, 12), (0.5, 2, 3)]:
            p, b = fixture()
            p['activities'][0]['quantity'] = sale_qty
            b['closing_positions'][0]['quantity'] = closing_qty
            p['activities'].append({'id': 'split', 'event_type': 'split', 'account_id': 'a',
                                    'holding_id': 'h', 'effective_at': '2026-01-10T00:00:00Z',
                                    'corporate_action': {'kind': 'split' if ratio >= 1 else 'reverse_split',
                                                         'exchange_ratio': ratio,
                                                         'legs': [{'holding_id': 'h', 'quantity_delta': 10 * (ratio - 1)}]}})
            with self.subTest(ratio=ratio):
                d = self.complete(self.calculate(p, b))
                self.assertEqual(d['realized_gain_base'], 200)
                self.assertEqual(d['holdings'][0]['remaining_cost_native'], 60)
                self.assertEqual(d['holdings'][0]['remaining_historical_cost_base'], 240)

    def test_split_correction_uses_full_replacement_and_retains_raw_lineage(self):
        p, b = fixture()
        p['activities'][0]['quantity'] = 8
        b['closing_positions'][0]['quantity'] = 12
        old = {'id': 'old-split', 'event_type': 'split', 'account_id': 'a', 'holding_id': 'h',
               'effective_at': '2026-01-10T00:00:00Z', 'ingested_at': '2026-01-10T00:00:00Z',
               'corporate_action': {'kind': 'split', 'exchange_ratio': 3,
                                    'legs': [{'holding_id': 'h', 'quantity_delta': 20}]}}
        new = copy.deepcopy(old)
        new.update(id='new-split', ingested_at=CUTOFF,
                   corporate_action={'kind': 'split', 'exchange_ratio': 2,
                                     'legs': [{'holding_id': 'h', 'quantity_delta': 10}]},
                   extensions={'rikdom_correction': {'version': 1, 'supersedes_activity_id': 'old-split', 'reason': 'ratio correction'}})
        p['activities'] += [old, new]
        d = self.complete(self.calculate(p, b))
        self.assertEqual(d['explained_result_base'], 550)
        self.assertEqual(len(d['history_evidence']['activities']), 3)
        self.assertEqual([r['activity_id'] for r in d['activity_evidence']], ['new-split', 'sale'])
        old['ingested_at'] = '2026-02-03T00:00:00Z'
        self.assertEqual(self.calculate(p, b)['decomposition']['status'], 'unavailable')

    def test_split_rejects_wrong_delta_basis_adjustment_and_same_instant_trade(self):
        p, b = fixture()
        split = {'id': 'split', 'event_type': 'split', 'account_id': 'a', 'holding_id': 'h',
                 'effective_at': '2026-01-10T00:00:00Z',
                 'corporate_action': {'kind': 'split', 'exchange_ratio': 2,
                                      'legs': [{'holding_id': 'h', 'quantity_delta': 10}]}}
        for mutation in ('delta', 'basis', 'time'):
            p, b = fixture()
            p['activities'][0]['quantity'] = 8
            b['closing_positions'][0]['quantity'] = 12
            current = copy.deepcopy(split)
            if mutation == 'delta':
                current['corporate_action']['legs'][0]['quantity_delta'] = 9
            elif mutation == 'basis':
                current['corporate_action']['legs'][0]['cost_basis_delta'] = {'amount': 10, 'currency': 'USD'}
            else:
                current['effective_at'] = SALE
            p['activities'].append(current)
            with self.subTest(mutation=mutation):
                self.assertEqual(self.calculate(p, b)['decomposition']['status'], 'unavailable')

    def test_missing_history_fx_stale_fx_and_late_fx_revision_fail_closed(self):
        original_document = copy.deepcopy(self.document)
        p, b = fixture()
        b['history']['missing_periods'] = ['2026-01']
        self.assertEqual(self.calculate(p, b)['decomposition']['status'], 'unavailable')
        p, b = fixture()
        self.document['series'][0]['observations'] = self.document['series'][0]['observations'][1:]
        self.assertEqual(self.calculate(p, b)['decomposition']['status'], 'unavailable')
        self.document = copy.deepcopy(original_document)
        self.document['series'][0]['observations'][2]['effective_at'] = '2026-01-14T00:00:00Z'
        self.assertEqual(self.calculate(p, b)['decomposition']['status'], 'unavailable')
        self.document = copy.deepcopy(original_document)
        original = self.document['series'][0]['observations'][0]
        self.document['series'][0]['observations'].append({**original, 'id': 'late', 'value': 4.5,
                                                         'retrieved_at': '2026-02-03T00:00:00Z', 'supersedes': original['id']})
        self.assertEqual(self.calculate(p, b, fx=self.fx(retrieved_before=None))['decomposition']['status'], 'unavailable')
        d = self.complete(self.calculate(p, b))
        self.assertEqual(d['explained_result_base'], 550)

    def test_fx_revision_provenance_is_detached_and_retained(self):
        original = self.document['series'][0]['observations'][0]
        self.document['series'][0]['observations'].append({**original, 'id': 'revision', 'value': 4.5,
                                                         'retrieved_at': '2026-01-01T00:00:00Z', 'supersedes': original['id']})
        p, b = fixture()
        d = self.complete(self.calculate(p, b))
        acquired = next(row['evidence'] for row in d['fx_evidence'] if row['purpose'] == 'opening_lot')
        self.assertEqual(acquired['observation']['id'], 'revision')
        self.assertEqual(acquired['superseded'][0]['id'], original['id'])
        self.assertEqual(d['realized_fx_gain_base'], 60)
        self.assertEqual(d['explained_result_base'], 550)
        acquired['observation']['value'] = 999
        self.assertEqual(self.complete(self.calculate(p, b))['realized_fx_gain_base'], 60)

    def test_native_cash_inventory_and_negative_or_oversold_positions_fail_closed(self):
        mutations = [lambda p, b: b['closing_cash'][0].update(amount=109),
                     lambda p, b: b['inventory']['cash'].clear(),
                     lambda p, b: b['inventory']['positions'].clear(),
                     lambda p, b: b['opening_positions'][0].update(quantity=-1),
                     lambda p, b: p['activities'][0].update(quantity=11),
                     lambda p, b: p['activities'][0].update(account_id='missing'),
                     lambda p, b: b['opening_lots'][0].update(total_cost_native=float('nan')),
                     lambda p, b: p['activities'][0].update(provenance={'bad': float('inf')})]
        for mutate in mutations:
            p, b = fixture()
            mutate(p, b)
            with self.subTest(mutate=mutate):
                result = self.calculate(p, b)
                self.assertEqual(result['decomposition']['status'], 'unavailable')
                self.assertIsNone(result['decomposition']['realized_fx_gain_base'])
                self.assertEqual(result['decomposition']['fx_evidence'], [])
        p, b = self.cash_only({'USD': 0}, {'USD': 0})
        p['activities'] = [self.event('debit', 'fee', 1), self.event('later-credit', 'income', 1,
                           effective_at='2026-01-16T00:00:00Z',
                           metadata={'rikdom_income': {'version': 1, 'amount_basis': 'net'}})]
        self.assertEqual(self.calculate(p, b, opening=0, closing=0)['decomposition']['status'], 'unavailable')

    def test_verified_internal_pair_conserves_each_account_and_never_becomes_external(self):
        p, b = self.cash_only({'USD': 50}, {'USD': 30})
        b['inventory']['account_ids'].append('b')
        b['inventory']['cash'].append({'account_id': 'b', 'currency': 'USD'})
        b['opening_cash'].append({'account_id': 'b', 'currency': 'USD', 'amount': 0})
        b['closing_cash'].append({'account_id': 'b', 'currency': 'USD', 'amount': 20})
        claim = {'version': 1, 'pair_id': 'transfer', 'review': {'status': 'reviewed',
                 'source': 'synthetic paired statements', 'reviewed_at': CUTOFF}}
        p['activities'] = [self.event('out', 'transfer_out', 20, metadata={'rikdom_internal_transfer': claim}),
                           self.event('in', 'transfer_in', 20, account_id='b', metadata={'rikdom_internal_transfer': claim})]
        result = self.calculate(p, b, opening=250, closing=350)
        d = self.complete(result)
        self.assertEqual(result['bridge']['net_external_cashflow_base'], 0)
        self.assertEqual(d['cash_fx_gain_base'], 100)
        # Preserve total cash while corrupting the individual accounts: cannot reconcile.
        b['closing_cash'][0]['amount'] = 31
        b['closing_cash'][1]['amount'] = 19
        self.assertEqual(self.calculate(p, b, opening=250, closing=350)['decomposition']['status'], 'unavailable')

    def test_source_retrieval_in_correction_lineage_cannot_exceed_cutoff(self):
        p, b = fixture()
        p['activities'][0]['extensions'] = {'source': {'retrieved_at': '2026-02-03T00:00:00Z'}}
        self.assertEqual(self.calculate(p, b)['decomposition']['status'], 'unavailable')


    def test_checked_in_offline_sample_reconciles_expected_components(self):
        root = Path(__file__).resolve().parents[1] / 'data-sample' / 'profit-attribution-fx'
        p = json.loads((root / 'portfolio.json').read_text())
        b = load_profit_basis(root / 'basis.json')
        fx = load_historical_fx(root / 'historical-fx.json', base_currency='BRL')
        snapshots = [json.loads(row) for row in (root / 'snapshots.jsonl').read_text().splitlines()]
        perf = compute_performance(snapshots, p['activities'], base_currency='BRL', historical_fx=fx)
        result = compute_profit_attribution(p, perf, basis=b, historical_fx=fx)
        d = self.complete(result)
        expected = json.loads((root / 'expected.json').read_text())
        self.assertEqual(result['bridge']['investment_result_base'], expected.pop('investment_result_base'))
        for key, value in expected.items():
            self.assertEqual(d[key], value, key)

    def test_malformed_split_cash_evidence_preserves_bridge_and_fails_decomposition(self):
        malformed = [None, [], 'zero', 0, {}, {'amount': 0},
                     {'amount': 0, 'currency': 'usd'}, {'amount': 0, 'currency': ''},
                     {'amount': 0, 'currency': 'USD', 'extra': True}]
        for field in ('money', 'fees', 'withholding_tax'):
            for value in malformed:
                p, b = fixture()
                p['activities'][0]['quantity'] = 8
                b['closing_positions'][0]['quantity'] = 12
                p['activities'].append({
                    'id': 'split', 'event_type': 'split', 'account_id': 'a', 'holding_id': 'h',
                    'effective_at': '2026-01-10T00:00:00Z', field: value,
                    'corporate_action': {'kind': 'split', 'exchange_ratio': 2,
                                         'legs': [{'holding_id': 'h', 'quantity_delta': 10}]}})
                with self.subTest(field=field, value=value):
                    result = self.calculate(p, b)
                    self.assertEqual(result['bridge']['status'], 'complete')
                    self.assertEqual(result['bridge']['investment_result_base'], 550)
                    self.assertEqual(result['decomposition']['status'], 'unavailable')
                    self.assertIsNone(result['decomposition']['explained_result_base'])
                    self.assertTrue(result['diagnostics'])

    def test_nested_source_review_after_cutoff_fails_but_later_basis_review_is_valid(self):
        p, b = fixture()
        b['review']['reviewed_at'] = '2026-02-11T00:00:00Z'
        self.complete(self.calculate(p, b))
        p['activities'][0]['extensions'] = {'source': {'review': {
            'status': 'reviewed', 'reviewed_at': '2026-02-10T00:00:00Z'}}}
        result = self.calculate(p, b)
        self.assertEqual(result['bridge']['status'], 'complete')
        self.assertEqual(result['decomposition']['status'], 'unavailable')
        self.assertIsNone(result['decomposition']['explained_result_base'])
        self.assertIn('retrieval cutoff', '; '.join(result['diagnostics']))

    def test_nested_split_correction_review_is_knowledge_even_without_ingestion_dates(self):
        p, b = fixture()
        p['activities'][0]['quantity'] = 8
        b['closing_positions'][0]['quantity'] = 12
        b['review']['reviewed_at'] = '2026-02-11T00:00:00Z'
        old = {'id': 'old-split', 'event_type': 'split', 'account_id': 'a', 'holding_id': 'h',
               'effective_at': '2026-01-10T00:00:00Z',
               'corporate_action': {'kind': 'split', 'exchange_ratio': 3,
                                    'legs': [{'holding_id': 'h', 'quantity_delta': 20}]}}
        new = copy.deepcopy(old)
        new.update(id='new-split',
                   corporate_action={'kind': 'split', 'exchange_ratio': 2,
                                     'legs': [{'holding_id': 'h', 'quantity_delta': 10}]},
                   extensions={
                       'rikdom_correction': {'version': 1, 'supersedes_activity_id': 'old-split',
                                             'reason': 'reviewed ratio correction'},
                       'rikdom_market_event': {'review': {'version': '1.1',
                           'reviewed_at': CUTOFF}}})
        p['activities'] += [old, new]
        self.complete(self.calculate(p, b))
        # The final projection has no generic knowledge timestamps; its nested
        # review still proves that this correction was not known at the cutoff.
        new['extensions']['rikdom_market_event']['review']['reviewed_at'] = '2026-02-10T00:00:00Z'
        result = self.calculate(p, b)
        self.assertEqual(result['bridge']['status'], 'complete')
        self.assertEqual(result['decomposition']['status'], 'unavailable')
        self.assertIsNone(result['decomposition']['explained_result_base'])
