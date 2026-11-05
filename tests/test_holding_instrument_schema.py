"""Schemas accept the explicit holding identity consumed by sourced market events."""
import copy
from importlib.resources import files
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


class HoldingInstrumentSchemaTests(unittest.TestCase):
    def validators(self):
        documents = {
            'canonical': Path('schema/portfolio.schema.json').read_text(),
            'packaged': files('rikdom._resources').joinpath('portfolio.schema.json').read_text(),
        }
        for name, document in documents.items():
            schema = json.loads(document)
            yield name, Draft202012Validator(
                {'$ref': '#/$defs/Holding', '$defs': schema['$defs']},
                format_checker=FormatChecker(),
            )

    def holding(self):
        return json.loads(Path('data-sample/historical-workflow/portfolio.json').read_text())['holdings'][0]

    def test_reviewed_market_event_holding_identity_and_legacy_rows_validate(self):
        holding = self.holding()
        legacy = copy.deepcopy(holding)
        legacy.pop('instrument')
        for name, validator in self.validators():
            with self.subTest(schema=name):
                self.assertEqual(list(validator.iter_errors(holding)), [])
                self.assertEqual(list(validator.iter_errors(legacy)), [])

    def test_malformed_or_ambiguous_holding_identities_are_rejected(self):
        valid = self.holding()['instrument']
        invalid = [None, 'ticker-only', {}, {**valid, 'namespace': ''},
                   {**valid, 'namespace': ' padded'}, {**valid, 'namespace': 'NS\n'},
                   {**valid, 'id': ' '}, {**valid, 'id': 'fund\n'},
                   {**valid, 'id': False}, {**valid, 'currency': 'usd'},
                   {**valid, 'currency': 'US'}, {**valid, 'currency': 'USD\n'}, {**valid, 'extra': 'ambiguous'}]
        for missing in ('namespace', 'id', 'currency'):
            identity = copy.deepcopy(valid)
            identity.pop(missing)
            invalid.append(identity)
        for name, validator in self.validators():
            for identity in invalid:
                holding = self.holding()
                holding['instrument'] = identity
                with self.subTest(schema=name, identity=identity):
                    self.assertTrue(list(validator.iter_errors(holding)))


if __name__ == '__main__':
    unittest.main()
