"""Local event inspection and explicit, validated atomic ledger application."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .market_events import apply_market_event, load_market_events, preview_market_event
from .market_series import _reject_constant, _unique_object
from .storage import save_json
from .validate import validate_portfolio


def _read(path: str) -> dict[str, Any]:
    with Path(path).open(encoding='utf-8') as stream:
        value = json.load(stream, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object: ' + path)
    return value


def _run(args: argparse.Namespace) -> int:
    write = args.event_command == 'apply' and args.write and not args.dry_run
    if write:
        target = Path(args.portfolio)
        for source_name in (args.input, args.review):
            source = Path(source_name)
            if target.resolve() == source.resolve() or (target.exists() and source.exists() and target.samefile(source)):
                raise ValueError(f'Applying market event would overwrite input {source}')
        # Atomic replacement of a symlink would replace the link rather than
        # its selected canonical target. Match read and write identity.
        args.portfolio = str(target.resolve())
    events = load_market_events(args.input)
    query = {'event_id': args.event, 'as_of': args.as_of, 'retrieved_before': args.retrieved_before}
    if args.event_command == 'lookup':
        result = events.lookup(**query)
    else:
        portfolio = _read(args.portfolio)
        errors = validate_portfolio(portfolio)
        if errors:
            raise ValueError('Invalid portfolio: ' + '; '.join(errors))
        review = _read(args.review) if args.review else None
        if args.event_command == 'preview':
            result = preview_market_event(portfolio, events, review=review, **query)
        else:
            candidate, result = apply_market_event(portfolio, events, review=review, **query)
            errors = validate_portfolio(candidate)
            if errors:
                raise ValueError('Invalid proposed portfolio: ' + '; '.join(errors))
            result = {**result, 'write': False, 'write_requested': args.write, 'dry_run': args.dry_run}
            if write and result['status'] == 'ready':
                save_json(args.portfolio, candidate)
                result['write'] = True
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


def register_market_events_command(subparsers: Any) -> None:
    """Register file-only commands; these never bootstrap or discover data."""
    parser = subparsers.add_parser('market-events', help='Inspect local events and preview reviewed ledger corrections')
    commands = parser.add_subparsers(dest='event_command', required=True)
    for action in ('lookup', 'preview', 'apply'):
        command = commands.add_parser(action)
        command.add_argument('--input', required=True, help='Versioned local event JSON')
        command.add_argument('--event', required=True, help='Exact event identity')
        command.add_argument('--as-of', required=True, help='UTC effective-time selection')
        command.add_argument('--retrieved-before', default=None, help='Inclusive UTC knowledge cutoff')
        if action != 'lookup':
            command.add_argument('--portfolio', required=True)
            command.add_argument('--review', required=action == 'apply', default=None, help='Explicit reviewed action evidence JSON')
        if action == 'apply':
            command.add_argument('--write', action='store_true', help='Atomically persist the validated ledger proposal')
            command.add_argument('--dry-run', action='store_true', help='Preview only, including when --write is supplied')
        command.set_defaults(func=_run)
