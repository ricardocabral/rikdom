#!/usr/bin/env python3
"""Educational, portfolio-only reader of captured performance runs, not a core API.

Replay a private snapshot with the existing core API; emit its unmodified result
and citations to the captured bytes. Explicit scratch space is required. No
canonical/saved inputs, reports, providers, plugins or credentials are written or
invoked. See docs/how-to/read-portfolio-context-example.md for trust limits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from tempfile import TemporaryDirectory, gettempdir
from typing import Any

from rikdom.analysis_runs import replay_analysis_run

MANIFEST = 'analysis-run.json'


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate key: {key}')
        result[key] = value
    return result


def _read_json(data: bytes, label: str, *, jsonl: bool = False) -> Any:
    """Refuse ambiguous JSON, nonfinite numbers and incomplete journal records."""
    try:
        if jsonl and data.strip() and not data.endswith(b'\n'):
            raise ValueError('JSONL must end with newline')
        rows = data.splitlines() if jsonl else [data]
        values = []
        for row in rows:
            if jsonl and not row.strip():
                continue
            value = json.loads(row, object_pairs_hook=_unique_object)
            if not isinstance(value, dict):
                raise ValueError('expected JSON object')
            json.dumps(value, allow_nan=False)
            values.append(value)
        return values if jsonl else values[0]
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'Invalid captured JSON: {label}: {exc}') from exc


def read_context(run: Path, scratch_dir: Path) -> dict[str, Any]:
    """Return portfolio context only after replaying the exact cited snapshot.

    scratch_dir must be an existing disposable directory outside canonical data
    and saved runs. The core also uses the OS temporary directory for replay.
    Neither location is a sandbox for untrusted installed Python.
    """
    run, scratch_dir = run.resolve(), scratch_dir.resolve()
    if not scratch_dir.is_dir():
        raise ValueError('Scratch directory must already exist outside canonical data and saved runs')
    if any(parent.is_relative_to(run) for parent in (scratch_dir, Path(gettempdir()).resolve())):
        raise ValueError('Scratch and OS temporary directories must be outside the saved run')
    manifest_bytes = (run / MANIFEST).read_bytes()
    manifest = _read_json(manifest_bytes, MANIFEST)
    if (manifest.get('format'), manifest.get('format_version'), manifest.get('operation')) != (
            'rikdom-analysis-run', '1.0', 'performance'):
        raise ValueError('Unsupported captured run format/version/operation; expected performance 1.0')
    # Replay assumes these objects exist. Validate their shapes explicitly rather
    # than masking AttributeError from replay or the calculation itself.
    for field in ('parameters', 'environment', 'inputs', 'methods', 'files'):
        if not isinstance(manifest.get(field), dict):
            raise ValueError(f'Invalid captured manifest: {field} must be an object')
    if not isinstance(manifest.get('created_at'), str) or not manifest['created_at'].strip():
        raise ValueError('Invalid captured manifest: created_at must be a nonempty string')
    parameters = manifest['parameters']
    if parameters.get('by') != 'portfolio':
        raise ValueError('Scope mismatch: this example requires a run captured with --by portfolio')
    for field in ('since', 'until', 'analysis_as_of', 'instrument'):
        value = parameters.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f'Invalid captured manifest: parameters.{field} must be a string or null')
    value = parameters.get('terminal_value')
    if value is not None and type(value) not in (int, float):
        raise ValueError('Invalid captured manifest: parameters.terminal_value must be a number or null')
    for key, relative in manifest['inputs'].items():
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError(f'Invalid captured manifest: inputs.{key} must be a nonempty path string')
    files = manifest['files']

    # Freeze each declared file once. Core replay verifies every copied byte and
    # recalculates from that snapshot, even if another process changes the run.
    with TemporaryDirectory(prefix='rikdom-context-', dir=scratch_dir) as temporary:
        snapshot = Path(temporary)
        (snapshot / MANIFEST).write_bytes(manifest_bytes)
        for relative, evidence in files.items():
            path = PurePosixPath(relative)
            if (not relative or '\\' in relative or path.is_absolute() or '..' in path.parts
                    or str(path) != relative or relative == MANIFEST
                    or not (run / relative).resolve().is_relative_to(run)):
                raise ValueError(f'Unsafe captured file path: {relative}')
            if not isinstance(evidence, dict):
                raise ValueError(f'Invalid captured file metadata: {relative} must be an object')
            if not isinstance(evidence.get('role'), str) or not evidence['role'].strip():
                raise ValueError(f'Invalid captured file metadata: {relative}: role must be a nonempty string')
            if type(evidence.get('bytes')) is not int or evidence['bytes'] < 0:
                raise ValueError(f'Invalid captured file metadata: {relative}: bytes must be a nonnegative integer')
            for field in ('sha256', 'original_sha256'):
                if field == 'original_sha256' and field not in evidence:
                    continue
                digest = evidence.get(field)
                if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
                    raise ValueError(f'Invalid captured file metadata: {relative}: {field} must be a SHA-256 hex digest')
            data = (run / relative).read_bytes()
            if path.suffix not in ('.json', '.jsonl'):
                raise ValueError(f'Unsupported captured evidence format: {relative}')
            _read_json(data, relative, jsonl=path.suffix == '.jsonl')
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        result = replay_analysis_run(snapshot)
        methods = {key: result[key] for key in (
            'twr_method', 'mwr_method', 'twr_return_basis', 'mwr_return_basis') if key in result}
        if manifest.get('methods') != methods:
            raise ValueError('Captured methods differ from reproduced result')

    return {
        'scope': 'portfolio',
        'capture': {
            'manifest': {'path': str(run / MANIFEST),
                         'sha256': hashlib.sha256(manifest_bytes).hexdigest()},
            'format': manifest['format'], 'format_version': manifest['format_version'],
            'operation': manifest['operation'], 'created_at': manifest['created_at'],
            'parameters': parameters, 'inputs': manifest['inputs'],
            'methods': manifest['methods'], 'environment': manifest['environment'],
            'files': {relative: {**evidence, 'path': str(run / relative)}
                      for relative, evidence in files.items()},
        },
        'result': result,
        'limitations': [
            'Reproduction verifies captured calculations, not completeness of portfolio history.',
            'Raw statuses, coverage, warnings and nulls apply to their documented fields only.',
            'Capture time is not an effective date or evidence that prices are current.',
            'Hashes detect inconsistent bytes, not authorship or disputed source facts.',
            'Canonical records, policy changes and proposed corrections require separate review.',
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True, help='Existing captured performance run directory')
    parser.add_argument('--scope', choices=['portfolio'], required=True,
                        help='Explicit scope; account/bucket/instrument selection is unsupported')
    parser.add_argument('--scratch-dir', type=Path, required=True,
                        help='Existing disposable directory outside canonical data and saved runs')
    args = parser.parse_args(argv)
    try:
        context = read_context(args.run, args.scratch_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Context read failed: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(context, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
