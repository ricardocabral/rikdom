"""Immutable, offline performance evidence. No providers or bundled code execute.

The run owns copied normalized inputs, relocatable local dependencies, the exact
CLI result, and a strict environment inventory. Replay verifies before calculation;
restore publishes a new directory only after integrity/compatibility checks.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from .export_bundle import ExportBundleError, read_verified_payloads, write_analysis_bundle
from .market_series import _unique_object, _reject_constant

RUN_MANIFEST = 'analysis-run.json'
INPUT_KEYS = {'portfolio', 'snapshots', 'fx_history', 'policy', 'historical_fx',
              'flow_valuations', 'historical_valuations', 'profit_basis', 'benchmarks_dir'}
PARAMETER_DEFAULTS = {'since': None, 'until': None, 'by': 'portfolio',
                      'instrument': None, 'terminal_value': None}


class AnalysisRunError(ValueError):
    """A captured run is unavailable, incompatible, or differs from its evidence."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':')) + '\n').encode('utf-8')


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _environment() -> dict[str, Any]:
    root = Path(__file__).parent
    core_files = sorted(p for p in root.rglob('*') if p.suffix in ('.py', '.json'))
    core = {p.relative_to(root).as_posix(): _digest(p.read_bytes()) for p in core_files}
    dependencies = {}
    for name in ('defusedxml', 'jsonschema', 'pluggy', 'quarto-cli', 'rfc3339-validator',
                 'attrs', 'jsonschema-specifications', 'referencing', 'rpds-py'):
        try:
            dependencies[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            dependencies[name] = None
    from . import __version__
    locks = {}
    for name in ('pyproject.toml', 'uv.lock'):
        candidate = root.parents[1] / name
        if candidate.is_file():
            locks[name] = _digest(candidate.read_bytes())
    return {'python': '.'.join(platform.python_version_tuple()[:2]),
            'implementation': platform.python_implementation(),
            'platform': platform.system(), 'core_version': metadata.version('rikdom'),
            'package_version': metadata.version('rikdom'), 'module_version': __version__,
            'dependency_lock_references': locks,
            'core_sha256': _digest(_json_bytes(core)), 'dependencies': dependencies,
            'plugins': [],
            'access': {'filesystem': 'captured local inputs only', 'network': 'not requested', 'credentials': 'not requested'}, 'plugin_execution': 'none; normalized inputs only',
            'trust_boundary': 'installed trusted Python core; no bundled code or provider access'}


def _relative(path: str) -> str:
    if (not isinstance(path, str) or not path or '\\' in path
            or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts
            or str(PurePosixPath(path)) != path):
        raise AnalysisRunError(f'Unsafe analysis dependency path: {path}')
    return path


def _local(root: Path, relative: str) -> Path:
    target = root / _relative(relative)
    if not target.resolve().is_relative_to(root.resolve()):
        raise AnalysisRunError(f'Analysis dependency escapes run: {relative}')
    return target


def _evaluate(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    # Use the public performance handler to retain its financial output contract.
    from .cli import cmd_performance
    args = {**PARAMETER_DEFAULTS, **manifest['parameters']}
    args.update({key: None for key in INPUT_KEYS})
    for key, value in manifest['inputs'].items():
        args[key] = str(_local(root, value))
    args['report_dir'] = None
    args['benchmarks_dir'] = args.get('benchmarks_dir') or str(root / 'inputs/benchmarks')
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cmd_performance(argparse.Namespace(**args))
    if code:
        raise AnalysisRunError('Analysis calculation failed: ' + err.getvalue().strip())
    return json.loads(out.getvalue())


def _strict_input(data: bytes, role: str, *, jsonl: bool = False) -> None:
    try:
        if jsonl:
            if data.strip() and not data.endswith(b'\n'):
                raise ValueError('JSONL must end with newline; repair the source explicitly')
            values = [json.loads(line, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                      for line in data.splitlines() if line.strip()]
            if any(not isinstance(row, dict) for row in values):
                raise ValueError('JSONL records must be objects')
        else:
            value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if not isinstance(value, dict):
                raise ValueError('expected JSON object')
    except (UnicodeError, ValueError) as exc:
        raise AnalysisRunError(f'Invalid analysis input {role}: {exc}') from exc


def _benchmark_dependencies(policy: dict[str, Any]) -> set[str]:
    from .benchmarks import _is_safe_benchmark_id
    benchmarks = {b['id']: b for b in policy.get('benchmarks', [])}
    leaves: set[str] = set()

    def visit(identifier: str, ancestors: frozenset[str] = frozenset()) -> None:
        if not isinstance(identifier, str) or not _is_safe_benchmark_id(identifier):
            raise AnalysisRunError('Unsafe benchmark dependency identifier')
        if identifier in ancestors or identifier not in benchmarks:
            raise AnalysisRunError(f'Missing or cyclic benchmark definition: {identifier}')
        benchmark = benchmarks[identifier]
        if benchmark.get('kind') == 'composite':
            for component in benchmark.get('components', []):
                visit(component['benchmark_id'], ancestors | {identifier})
        else:
            leaves.add(identifier)

    for target in (policy.get('strategic_allocation') or {}).get('targets', []):
        if target.get('benchmark_id'):
            visit(target['benchmark_id'])
    return leaves


def capture_performance_run(output: str | Path, *, inputs: dict[str, str | Path],
                            parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Capture and calculate using copied inputs, then atomically publish a new run."""
    output = Path(output)
    if output.exists():
        raise AnalysisRunError(f'Refusing to replace existing analysis run: {output}')
    unknown = set(inputs) - INPUT_KEYS
    parameters = parameters or {}
    unknown |= set(parameters) - set(PARAMETER_DEFAULTS) - {'analysis_as_of'}
    if unknown:
        raise AnalysisRunError('Unsupported analysis options: ' + ', '.join(sorted(unknown)))
    if 'portfolio' not in inputs:
        raise AnalysisRunError('Analysis input missing: portfolio')
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.analysis-', dir=output.parent) as stage:
        root = Path(stage) / 'run'
        root.mkdir()
        files: dict[str, dict[str, Any]] = {}
        mapped: dict[str, str] = {}
        policy = json.loads(Path(inputs['policy']).read_bytes()) if 'policy' in inputs else {}
        benchmark_ids = _benchmark_dependencies(policy)

        def put(relative: str, data: bytes, role: str) -> None:
            path = _local(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files[relative] = {'sha256': _digest(data), 'bytes': len(data), 'role': role}

        for key, source in sorted(inputs.items()):
            source = Path(source)
            if key == 'benchmarks_dir':
                if not source.is_dir():
                    raise AnalysisRunError('Analysis dependency missing: benchmarks_dir')
                mapped[key] = 'inputs/benchmarks'
                (root / mapped[key]).mkdir(parents=True, exist_ok=True)
                for identifier in sorted(benchmark_ids):
                    item = source / f'{identifier}.jsonl'
                    if not item.is_file() or not item.resolve().is_relative_to(source.resolve()):
                        raise AnalysisRunError(f'Analysis dependency missing: benchmark {identifier}')
                    data = item.read_bytes()
                    _strict_input(data, 'benchmark ' + identifier, jsonl=True)
                    put(f'inputs/benchmarks/{item.name}', data, 'benchmark')
                continue
            if not source.is_file():
                raise AnalysisRunError(f'Analysis dependency missing: {key}')
            suffix = '.jsonl' if key in ('snapshots', 'fx_history') else '.json'
            relative = f'inputs/{key}{suffix}'
            data = source.read_bytes()
            _strict_input(data, key, jsonl=suffix == '.jsonl')
            original_sha256 = _digest(data)
            if key in ('historical_fx', 'historical_valuations'):
                config = json.loads(data)
                series = Path(config['market_series_file'])
                if not series.is_absolute():
                    series = source.parent / series
                nested = f'inputs/{key}-series.json'
                if not series.is_file():
                    raise AnalysisRunError(f'Analysis dependency missing: {key}.market_series_file')
                series_data = series.read_bytes()
                _strict_input(series_data, key + '.market_series_file')
                put(nested, series_data, key + '.market_series_file')
                config['market_series_file'] = Path(nested).name
                data = _json_bytes(config)
            put(relative, data, key)
            mapped[key] = relative
            files[relative]['original_sha256'] = original_sha256
        if benchmark_ids and 'benchmarks_dir' not in mapped:
            raise AnalysisRunError('Analysis dependency missing: benchmarks_dir')
        for key in ('snapshots', 'fx_history'):
            if key not in mapped:
                relative = f'inputs/{key}.jsonl'
                put(relative, b'', key)
                mapped[key] = relative
        manifest = {'format': 'rikdom-analysis-run', 'format_version': '1.0',
                    'operation': 'performance', 'replayable': True,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'parameters': {**PARAMETER_DEFAULTS,
                                   'analysis_as_of': datetime.now(timezone.utc).isoformat(), **parameters},
                    'inputs': mapped, 'files': files, 'environment': _environment()}
        result = _evaluate(root, manifest)
        manifest['methods'] = {key: result[key] for key in
                               ('twr_method', 'mwr_method', 'twr_return_basis', 'mwr_return_basis')
                               if key in result}
        put('result.json', _json_bytes(result), 'expected_result')
        manifest['output_sha256'] = files['result.json']['sha256']
        (root / RUN_MANIFEST).write_bytes(_json_bytes(manifest))
        root.rename(output)
    return manifest


def _read_verified_run(run: str | Path, *, check_environment: bool = True) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Validate declared bytes; evidence comparison may skip runtime compatibility.

    Skipping compatibility permits inspection only, never calculation or restore.
    Callers receive the verified bytes so subsequent reads cannot change evidence.
    """
    root = Path(run)
    manifest_bytes = (root / RUN_MANIFEST).read_bytes()
    _strict_input(manifest_bytes, RUN_MANIFEST)
    manifest = json.loads(manifest_bytes)
    payloads = {RUN_MANIFEST: manifest_bytes}
    if (manifest.get('format'), manifest.get('format_version'), manifest.get('operation')) != (
            'rikdom-analysis-run', '1.0', 'performance'):
        raise AnalysisRunError('Unsupported analysis manifest or operation')
    if manifest.get('replayable') is not True:
        raise AnalysisRunError('Required analysis evidence omitted; redacted export cannot replay')
    if set(manifest.get('parameters', {})) != set(PARAMETER_DEFAULTS) | {'analysis_as_of'}:
        raise AnalysisRunError('Unsupported or missing analysis parameters')
    inputs = manifest.get('inputs', {})
    if set(inputs) - INPUT_KEYS or not {'portfolio', 'snapshots', 'fx_history'} <= set(inputs):
        raise AnalysisRunError('Unsupported or missing analysis inputs')
    files = manifest.get('files', {})
    if not isinstance(files, dict) or 'result.json' not in files:
        raise AnalysisRunError('Expected analysis result missing')
    for relative, evidence in files.items():
        path = _local(root, relative)
        if not path.is_file():
            raise AnalysisRunError(f'Analysis dependency missing: {relative}')
        data = path.read_bytes()
        if len(data) != evidence['bytes'] or _digest(data) != evidence['sha256']:
            raise AnalysisRunError(f'Analysis dependency changed: {relative}')
        _strict_input(data, relative, jsonl=relative.endswith('.jsonl'))
        payloads[relative] = data
    for key, relative in inputs.items():
        _local(root, relative)
        if key != 'benchmarks_dir' and relative not in files:
            raise AnalysisRunError(f'Analysis dependency omitted: {key}')
        if key in ('historical_fx', 'historical_valuations'):
            config = json.loads(payloads[relative])
            nested = (PurePosixPath(relative).parent / config['market_series_file']).as_posix()
            _relative(nested)
            if nested not in files:
                raise AnalysisRunError(f'Analysis dependency omitted: {key}.market_series_file')
    if inputs.get('policy'):
        policy = json.loads(payloads[inputs['policy']])
        for identifier in _benchmark_dependencies(policy):
            relative = inputs.get('benchmarks_dir', '') + '/' + identifier + '.jsonl'
            if relative not in files:
                raise AnalysisRunError(f'Analysis dependency omitted: benchmark {identifier}')
    if manifest.get('output_sha256') != files['result.json']['sha256']:
        raise AnalysisRunError('Expected analysis output hash changed')
    if check_environment:
        installed = _environment()
        for key in ('python', 'implementation', 'platform', 'core_version', 'core_sha256', 'dependencies', 'plugins', 'package_version', 'module_version'):
            if manifest.get('environment', {}).get(key) != installed[key]:
                raise AnalysisRunError(f'Analysis environment incompatible: {key}; install the recorded trusted environment separately')
    return manifest, payloads


def replay_analysis_run(run: str | Path) -> dict[str, Any]:
    manifest, payloads = _read_verified_run(run)
    with TemporaryDirectory(prefix='rikdom-replay-') as temporary:
        root = Path(temporary)
        for name, data in payloads.items():
            target = _local(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        result = _evaluate(root, manifest)
    if _digest(_json_bytes(result)) != manifest['output_sha256']:
        raise AnalysisRunError('Analysis output differs from captured result')
    return result


def export_analysis_run(run: str | Path, output: str | Path, *, redacted: bool = False,
                        dry_run: bool = False, omit_inputs: list[str] | None = None,
                        omission_reason: str = 'user') -> dict[str, Any]:
    manifest, verified = _read_verified_run(run)
    output_resolved = Path(output).resolve()
    if output_resolved.is_relative_to(Path(run).resolve()):
        raise AnalysisRunError('Export output must be outside the immutable analysis run')
    omitted_roles = set(omit_inputs or [])
    known_roles = {evidence['role'] for evidence in manifest['files'].values()} - {'expected_result'}
    if omitted_roles - known_roles:
        raise AnalysisRunError('Unknown omitted input role: ' + ', '.join(sorted(omitted_roles - known_roles)))
    if omitted_roles:
        manifest['omitted'] = []
        manifest['replayable'] = False
        for name, evidence in list(manifest['files'].items()):
            if evidence['role'] in omitted_roles:
                manifest['omitted'].append({'path': name, 'sha256': evidence['sha256'], 'reason': omission_reason})
                del manifest['files'][name]
    if redacted:
        manifest = {'format': manifest['format'], 'format_version': '1.0',
                    'operation': 'performance', 'replayable': False,
                    'omitted': ['normalized inputs', 'parameters', 'financial results', 'source references'],
                    'environment': manifest['environment'], 'methods': manifest['methods']}
    preview = {'replayable': manifest['replayable'], 'manifest': manifest,
               'files': [RUN_MANIFEST] if redacted else [RUN_MANIFEST, *manifest['files']]}
    if not dry_run:
        payloads = {RUN_MANIFEST: _json_bytes(manifest)}
        if not redacted:
            payloads.update({name: verified[name] for name in manifest['files']})
        write_analysis_bundle(output, payloads)
    return preview


def restore_analysis_run(bundle: str | Path, output: str | Path) -> dict[str, Any]:
    output = Path(output)
    if output.exists():
        raise AnalysisRunError(f'Refusing to replace existing analysis run: {output}')
    _, payloads = read_verified_payloads(bundle)
    if 'analysis_manifest' not in payloads:
        raise AnalysisRunError('Bundle contains no captured analysis run')
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.restore-', dir=output.parent) as stage:
        root = Path(stage) / 'run'
        root.mkdir()
        for name, data in payloads.items():
            relative = RUN_MANIFEST if name == 'analysis_manifest' else name.removeprefix('analysis/')
            path = _local(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        manifest = json.loads((root / RUN_MANIFEST).read_bytes())
        if manifest.get('replayable') is True:
            _read_verified_run(root)
        elif ((manifest.get('format'), manifest.get('format_version'), manifest.get('operation'))
              != ('rikdom-analysis-run', '1.0', 'performance')
              or manifest.get('replayable') is not False or not manifest.get('omitted')):
            raise AnalysisRunError('Invalid incomplete analysis manifest')
        root.rename(output)
    return manifest


def cmd_analysis(args: argparse.Namespace) -> int:
    try:
        if args.command == 'capture-analysis':
            inputs = {key: getattr(args, key) for key in INPUT_KEYS
                      if getattr(args, key, None) is not None}
            if 'policy' not in inputs:
                inputs.pop('benchmarks_dir', None)
            result = capture_performance_run(args.output, inputs=inputs,
                parameters={key: getattr(args, key, value) for key, value in PARAMETER_DEFAULTS.items()})
        elif args.command == 'replay-analysis':
            result = replay_analysis_run(args.run)
        elif args.command == 'export-analysis':
            result = export_analysis_run(args.run, args.output, redacted=args.redacted, dry_run=args.dry_run,
                omit_inputs=args.omit_input, omission_reason=args.omission_reason)
        else:
            result = restore_analysis_run(args.bundle, args.output)
    except (OSError, ValueError, KeyError, TypeError, ExportBundleError, zipfile.BadZipFile) as exc:
        import sys
        print(f'Analysis failed: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0
