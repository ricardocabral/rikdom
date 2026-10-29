"""Report writes must preserve selected local evidence, including file aliases."""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from rikdom.cli import main
from rikdom.plugin_engine.pipeline import run_output_pipeline


ARTIFACTS = (
    'quarto-input.json', 'report-data.js', 'holding_trust.json', 'holding_trust.md',
    'reconciliation.json', 'reconciliation.md', 'dashboard.html', 'portfolio-report.html',
)


class ReportInputProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = self.root / 'inputs'
        self.portfolio = self.inputs / 'portfolio.json'
        self.snapshots = self.inputs / 'snapshots.jsonl'
        self.output = self.root / 'output'
        self.reset_case()
        disable_quarto = patch.dict(os.environ, {'RIKDOM_DISABLE_QUARTO': '1'})
        disable_quarto.start()
        self.addCleanup(disable_quarto.stop)

    def reset_case(self):
        self.inputs = self.root / 'inputs'
        self.output = self.root / 'output'
        for path in (self.inputs, self.output):
            if path.exists():
                shutil.rmtree(path)
        shutil.copytree('data-sample/performance-fx', self.inputs)
        self.output.mkdir()

    def embedded(self, **options):
        portfolio = json.loads(self.portfolio.read_text())
        portfolio['extensions'] = {'rikdom_report': {'performance': options}}
        self.portfolio.write_text(json.dumps(portfolio))

    def run_pipeline(self, options=None):
        return run_output_pipeline(
            plugin_name='quarto-portfolio-report', plugins_dir='plugins',
            portfolio_path=str(self.portfolio), snapshots_path=str(self.snapshots),
            output_dir=str(self.output), options=options,
        )

    def assert_rejected_without_writes(self, selected, *, options=None):
        before = {path: path.read_bytes() for path in selected}
        output_before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        error = None
        try:
            self.run_pipeline(options)
        except ValueError as exc:
            error = exc
        self.assertEqual({path: path.read_bytes() for path in selected}, before,
                         'report changed selected input bytes')
        self.assertEqual({path.name: path.read_bytes() for path in self.output.iterdir()}, output_before,
                         'report wrote artifacts before rejecting the input collision')
        self.assertIsNotNone(error, 'report must reject an input/output collision')
        self.assertIn('overwrite', str(error).lower())

    def test_every_fixed_artifact_rejects_invalid_selected_input_before_any_write(self):
        for name in ARTIFACTS:
            with self.subTest(name=name):
                self.reset_case()
                sidecar = self.output / name
                sidecar.write_text('{"invalid": "selected profit basis"}')
                self.embedded(profit_basis_path=str(sidecar))
                self.assert_rejected_without_writes([self.portfolio, self.snapshots, sidecar])
                sidecar.unlink()

    def test_all_selected_embedded_and_override_sidecars_are_protected(self):
        for option, embedded_key in (
            ('flow_valuations', 'flow_valuations_path'), ('historical_fx', 'historical_fx_path'),
            ('historical_valuations', 'historical_valuations_path'), ('profit_basis', 'profit_basis_path'),
            ('policy', 'policy_path'), ('fx_history', 'fx_history_path'),
        ):
            for embedded in (True, False):
                with self.subTest(option=option, embedded=embedded):
                    self.reset_case()
                    sidecar = self.output / 'dashboard.html'
                    sidecar.write_text('{"invalid": "selected input"}')
                    self.embedded(**({embedded_key: '../output/dashboard.html'} if embedded else {}))
                    options = None if embedded else {option: str(sidecar)}
                    self.assert_rejected_without_writes([self.portfolio, self.snapshots, sidecar], options=options)
                    sidecar.unlink()

    def test_portfolio_and_snapshots_are_protected_in_library_pipeline(self):
        for field in ('portfolio', 'snapshots'):
            with self.subTest(field=field):
                self.reset_case()
                original = getattr(self, field)
                alias = self.output / 'reconciliation.json'
                alias.symlink_to(original)
                self.assert_rejected_without_writes([self.portfolio, self.snapshots])
                alias.unlink()

    def test_output_symlinks_and_hardlinks_cannot_overwrite_selected_sidecars(self):
        for kind in ('symlink', 'hardlink'):
            for option in ('flow_valuations_path', 'historical_fx_path', 'profit_basis_path'):
                with self.subTest(kind=kind, option=option):
                    self.reset_case()
                    sidecar = self.inputs / 'sidecar.json'
                    sidecar.write_text('{"invalid": "selected input"}')
                    alias = self.output / 'dashboard.html'
                    if kind == 'symlink':
                        alias.symlink_to(sidecar)
                    else:
                        os.link(sidecar, alias)
                    self.embedded(**{option: 'sidecar.json'})
                    self.assert_rejected_without_writes([self.portfolio, self.snapshots, sidecar])
                    alias.unlink()

    def test_nested_market_series_paths_are_protected_even_for_invalid_configs(self):
        for option in ('historical_fx_path', 'historical_valuations_path'):
            for kind in ('direct', 'symlink', 'hardlink'):
                with self.subTest(option=option, kind=kind):
                    self.reset_case()
                    config_dir = self.inputs / 'nested'
                    config_dir.mkdir(exist_ok=True)
                    config = config_dir / 'config.json'
                    cache = self.output / 'report-data.js'
                    cache.write_text('{"invalid": "selected cache"}')
                    if kind == 'direct':
                        reference = '../../output/report-data.js'
                    else:
                        alias = config_dir / 'cache.json'
                        if kind == 'symlink':
                            alias.symlink_to(cache)
                        else:
                            os.link(cache, alias)
                        reference = 'cache.json'
                    config.write_text(json.dumps({'market_series_file': reference, 'invalid': True}))
                    self.embedded(**{option: 'nested/config.json'})
                    self.assert_rejected_without_writes([self.portfolio, self.snapshots, config, cache])
                    cache.unlink()
                    if kind != 'direct':
                        alias.unlink()

    def test_selected_benchmark_cache_alias_is_protected(self):
        benchmarks = self.inputs / 'benchmarks'
        benchmarks.mkdir()
        benchmark = benchmarks / 'idx.jsonl'
        benchmark.write_text('{"as_of":"2026-07-01","level":100,"currency":"BRL"}\n')
        policy = self.inputs / 'policy.json'
        policy.write_text(json.dumps({'benchmarks': [{'id': 'idx'}]}))
        os.link(benchmark, self.output / 'holding_trust.md')
        self.embedded(policy_path='policy.json', benchmarks_dir='benchmarks')
        self.assert_rejected_without_writes([self.portfolio, self.snapshots, policy, benchmark])

    def test_cli_custom_target_is_checked_before_report_artifacts(self):
        for kind in ('direct', 'symlink', 'hardlink'):
            with self.subTest(kind=kind):
                self.reset_case()
                target = self.output / 'custom.json'
                sidecar = self.inputs / 'flow-valuations.json'
                if kind == 'direct':
                    shutil.copy2(sidecar, target)
                    selected = target
                else:
                    selected = sidecar
                    if kind == 'symlink':
                        target.symlink_to(selected)
                    else:
                        os.link(selected, target)
                before = selected.read_bytes()
                errors = io.StringIO()
                with redirect_stderr(errors), redirect_stdout(io.StringIO()):
                    result = main(['viz', '--portfolio', str(self.portfolio), '--snapshots', str(self.snapshots),
                                   '--flow-valuations', str(selected), '--out', str(target)])
                self.assertEqual(selected.read_bytes(), before, 'custom --out overwrote selected evidence')
                self.assertEqual(set(path.name for path in self.output.iterdir()), {'custom.json'})
                self.assertEqual(result, 1)
                self.assertIn('overwrite', errors.getvalue().lower())
                target.unlink()

    def test_supported_colocation_and_separate_output_keep_valid_evidence_unchanged(self):
        for colocated in (False, True):
            with self.subTest(colocated=colocated):
                self.reset_case()
                self.output = self.inputs if colocated else self.root / 'output'
                self.embedded(historical_fx_path='historical-fx.json', flow_valuations_path='flow-valuations.json')
                before = {path: path.read_bytes() for path in self.inputs.iterdir() if path.is_file()}
                self.run_pipeline()
                payload = json.loads((self.output / 'quarto-input.json').read_text())
                self.assertEqual(payload['sections']['performance']['twr_return_pct'], 21)
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                self.assertTrue(all((self.output / name).is_file() for name in ARTIFACTS))

    def test_explicit_benchmarks_directory_applies_to_embedded_policy(self):
        policy = self.inputs / 'policy.json'
        policy.write_text(json.dumps({
            'benchmarks': [{'id': 'idx', 'kind': 'index', 'currency': 'BRL'}],
            'strategic_allocation': {'targets': [{'dimension': 'asset_class', 'bucket': 'stocks',
                                                  'weight_pct': 100, 'benchmark_id': 'idx'}]},
        }))
        self.embedded(policy_path='policy.json')
        benchmarks = self.root / 'chosen-benchmarks'
        benchmarks.mkdir()
        (benchmarks / 'idx.jsonl').write_text(
            '{"as_of":"2026-07-01","level":100,"currency":"BRL"}\n'
            '{"as_of":"2026-07-03","level":110,"currency":"BRL"}\n')
        errors = io.StringIO()
        with redirect_stderr(errors), redirect_stdout(io.StringIO()):
            result = main(['viz', '--portfolio', str(self.portfolio), '--snapshots', str(self.snapshots),
                           '--benchmarks-dir', str(benchmarks), '--out', str(self.output / 'dashboard.html')])
        self.assertEqual(result, 0, errors.getvalue())
        sections = json.loads((self.output / 'quarto-input.json').read_text())['sections']
        self.assertEqual(sections['performance']['benchmarks'][0]['twr_pct'], 10)
        self.assertEqual(sections['performance_context']['inputs']['benchmarks_dir'], 'chosen-benchmarks')

    def test_valid_nested_market_series_inputs_are_protected(self):
        for option, folder, filename in (
            ('historical_fx_path', 'performance-fx', 'historical-fx.json'),
            ('historical_valuations_path', 'historical-valuation-replay', 'replay.json'),
        ):
            with self.subTest(option=option):
                self.reset_case()
                config_dir = self.inputs / 'nested'
                config_dir.mkdir()
                config = json.loads((Path('data-sample') / folder / filename).read_text())
                cache_source = Path('data-sample') / folder / config['market_series_file']
                cache = self.output / 'quarto-input.json'
                shutil.copy2(cache_source, cache)
                config['market_series_file'] = '../../output/quarto-input.json'
                config_path = config_dir / 'config.json'
                config_path.write_text(json.dumps(config))
                self.embedded(**{option: 'nested/config.json'})
                self.assert_rejected_without_writes([self.portfolio, self.snapshots, config_path, cache])

    def test_cli_custom_target_protects_canonical_inputs_and_nested_caches(self):
        for source in ('portfolio', 'snapshots', 'cache'):
            with self.subTest(source=source):
                self.reset_case()
                if source == 'cache':
                    selected = self.output / 'local-cache.json'
                    shutil.copy2(self.inputs / 'market-series.json', selected)
                    config = json.loads((self.inputs / 'historical-fx.json').read_text())
                    config['market_series_file'] = '../output/local-cache.json'
                    (self.inputs / 'historical-fx.json').write_text(json.dumps(config))
                    self.embedded(historical_fx_path='historical-fx.json')
                else:
                    selected = getattr(self, source)
                before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
                errors = io.StringIO()
                with redirect_stderr(errors), redirect_stdout(io.StringIO()):
                    result = main(['viz', '--portfolio', str(self.portfolio), '--snapshots', str(self.snapshots),
                                   '--out', str(selected)])
                after = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
                self.assertEqual(after, before)
                self.assertEqual(result, 1)
                self.assertIn('overwrite', errors.getvalue().lower())

    def test_cli_include_current_preserves_original_snapshot_and_fx_inputs(self):
        for source in ('snapshots', 'fx_history'):
            with self.subTest(source=source):
                self.reset_case()
                fx_history = self.inputs / 'fx_rates.jsonl'
                fx_history.write_text('')
                selected = self.snapshots if source == 'snapshots' else fx_history
                # Performance can select a different FX history; --include-current
                # still reads the CLI-selected default to value current holdings.
                self.embedded(fx_history_path='other-fx.jsonl')
                alias = self.output / 'dashboard.html'
                os.link(selected, alias)
                before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
                errors = io.StringIO()
                with redirect_stderr(errors), redirect_stdout(io.StringIO()):
                    result = main(['viz', '--portfolio', str(self.portfolio), '--snapshots', str(self.snapshots),
                                   '--data-dir', str(self.inputs), '--include-current', '--out', str(alias)])
                self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, before)
                self.assertEqual(result, 1)
                self.assertIn('overwrite', errors.getvalue().lower())

    def test_override_precedence_does_not_reject_unselected_colliding_sidecar(self):
        self.embedded(flow_valuations_path='../output/dashboard.html', historical_fx_path='historical-fx.json')
        (self.output / 'dashboard.html').write_text('{"unused": "overridden sidecar"}')
        self.run_pipeline({'flow_valuations': str(self.inputs / 'flow-valuations.json')})
        payload = json.loads((self.output / 'quarto-input.json').read_text())
        self.assertEqual(payload['sections']['performance']['twr_return_pct'], 21)

    def test_unknown_preference_does_not_disable_input_protection(self):
        selected = self.output / 'dashboard.html'
        selected.write_text('{"invalid": "selected sidecar"}')
        self.embedded(profit_basis_path=str(selected), unknown_option='invalid')
        self.assert_rejected_without_writes([self.portfolio, self.snapshots, selected])

    @unittest.skipUnless(shutil.which('quarto') or Path(sys.executable).with_name('quarto').is_file(),
                         'Real Quarto regression requires the installed renderer')
    def test_real_quarto_asset_copy_cannot_overwrite_selected_market_series(self):
        config = json.loads((self.inputs / 'historical-fx.json').read_text())
        asset = self.output / 'dashboard_files/libs/clipboard/clipboard.min.js'
        asset.parent.mkdir(parents=True)
        shutil.copy2(self.inputs / 'market-series.json', asset)
        config['market_series_file'] = '../output/dashboard_files/libs/clipboard/clipboard.min.js'
        (self.inputs / 'historical-fx.json').write_text(json.dumps(config))
        self.embedded(historical_fx_path='historical-fx.json')
        before = asset.read_bytes()
        error = None
        with patch.dict(os.environ):
            os.environ.pop('RIKDOM_DISABLE_QUARTO', None)
            try:
                self.run_pipeline()
            except ValueError as exc:
                error = exc
        self.assertEqual(asset.read_bytes(), before, 'Quarto replaced selected market-series cache with JavaScript')
        self.assertIsNotNone(error)
        self.assertIn('overwrite', str(error).lower())

    def test_owned_quarto_asset_trees_protect_resolved_paths_and_file_aliases(self):
        for folder in ('report_files', 'dashboard_files'):
            for kind in ('inside', 'directory_symlink', 'file_symlink', 'hardlink'):
                with self.subTest(folder=folder, kind=kind):
                    self.reset_case()
                    tree = self.output / folder
                    selected = self.inputs / 'cache.json'
                    if kind == 'inside':
                        tree.mkdir()
                        selected = tree / 'cache.json'
                        selected.write_text('{}')
                    else:
                        selected.write_text('{}')
                        if kind == 'directory_symlink':
                            tree.symlink_to(self.inputs, target_is_directory=True)
                        else:
                            tree.mkdir()
                            alias = tree / 'asset.js'
                            if kind == 'file_symlink':
                                alias.symlink_to(selected)
                            else:
                                os.link(selected, alias)
                    self.embedded(profit_basis_path=str(selected))
                    before = {path: path.read_bytes() for path in self.inputs.rglob('*') if path.is_file()}
                    with self.assertRaisesRegex(ValueError, 'overwrite'):
                        self.run_pipeline()
                    self.assertEqual({path: path.read_bytes() for path in before}, before)
                    self.assertFalse((self.output / 'holding_trust.json').exists())

    def test_safe_colocation_in_adjacent_unowned_directory_is_supported(self):
        adjacent = self.output / 'reviewed-evidence'
        adjacent.mkdir()
        shutil.copy2(self.inputs / 'flow-valuations.json', adjacent / 'flows.json')
        before = (adjacent / 'flows.json').read_bytes()
        self.embedded(historical_fx_path='historical-fx.json',
                      flow_valuations_path='../output/reviewed-evidence/flows.json')
        self.run_pipeline()
        self.assertEqual((adjacent / 'flows.json').read_bytes(), before)
        payload = json.loads((self.output / 'quarto-input.json').read_text())
        self.assertEqual(payload['sections']['performance']['twr_return_pct'], 21)

    def test_override_config_symlink_uses_resolved_config_directory_for_cache(self):
        config_dir = self.inputs / 'nested'
        config_dir.mkdir()
        config = config_dir / 'config.json'
        cache = self.output / 'report-data.js'
        cache.write_text('{"invalid": "selected cache"}')
        config.write_text(json.dumps({'market_series_file': '../../output/report-data.js'}))
        selected = self.inputs / 'fx-link.json'
        selected.symlink_to(config)
        self.assert_rejected_without_writes(
            [self.portfolio, self.snapshots, config, cache], options={'historical_fx': str(selected)},
        )

    def test_selected_benchmark_symlink_remains_protected_when_loader_rejects_it(self):
        benchmarks = self.inputs / 'benchmarks'
        benchmarks.mkdir()
        cache = self.output / 'report-data.js'
        cache.write_text('{"invalid": "benchmark input"}')
        (benchmarks / 'idx.jsonl').symlink_to(cache)
        policy = self.inputs / 'policy.json'
        policy.write_text(json.dumps({'benchmarks': [{'id': 'idx'}]}))
        self.embedded(policy_path='policy.json', benchmarks_dir='benchmarks')
        self.assert_rejected_without_writes([self.portfolio, self.snapshots, policy, cache])
