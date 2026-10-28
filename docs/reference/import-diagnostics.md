# Import diagnostics and source identity

Source plugins emit `metadata.rikdom_import_diagnostics` with `version: 1`,
`history_coverage`, and `unsupported_events`. All first-party source hooks declare
these fields. Older third-party plugins receive explicit unknown coverage.

## Coverage

Each coverage entry has an opaque `scope`, `status` (`complete`, `partial`, or
`unknown`), and `event_types`. A complete period requires ISO `from`/`through`
dates. Source-calendar dates are inclusive; timezone interpretation belongs to
the source plugin. Core validates declared facts rather than guessing a locale.
See the [quantity evidence example](../how-to/enter-and-correct-activities.md#declare-the-evidence-for-a-quantity-comparison).

Observed transaction limits do not prove the source's coverage. Import coverage
does not automatically mark a holding's instrument-return history complete.
Independent statements remain separate evidence; overlapping periods are not
automatically joined into complete lifetime coverage.

Each unsupported event has `source_ref`, `source_event`, and `reason`, with optional
`scope`, `affects_quantity`, and `affects_cash`. Empty means none observed in the
provided input; it is not a claim that the importer supports every possible event.

Successful writes preserve evidence under
`portfolio.extensions.rikdom_import_diagnostics.statements`, keyed by provider and
document fingerprint. Full run diagnostics are also in `import_log.jsonl`.
Generated reports can therefore show coverage without the original statement or log.

## Anonymous event identities

Plugins may emit `activity.metadata.rikdom_source_identity`:

```json
{
  "version": 1,
  "scope": "opaque-provider-account",
  "document_fingerprint": "opaque-normalized-document-fingerprint",
  "signature": "opaque-normalized-economic-row-signature",
  "occurrence": 0,
  "kind": "anonymous"
}
```

`kind` is `source`, `anonymous`, or `reviewed`. `source` means the identity is backed
by a source event/execution identifier. For anonymous rows, the plugin constructs
the fingerprint from a sorted multiset of normalized rows, retaining identical-row
multiplicity while ignoring row order and run timestamps. Core does not interpret
source columns, ticker conventions, or account naming rules.

The same document occurrence must retain its ID/key. Another document with
overlapping anonymous signatures in the same scope blocks before writing.
This preserves legitimate identical executions without guessing whether an
overlapping row describes an old execution or an additional one.

## Reviewed recovery

Prepare a normalized statement containing full copies of the already stored
events with their existing IDs/keys and the confirmed additional events with new
IDs/keys. Retain original source identity/provenance on the existing events;
additional reviewed events carry the affected document fingerprint and `kind:
"reviewed"`. Add this diagnostic field:

```json
{
  "identity_resolution": {
    "scope": "opaque-provider-account",
    "document_fingerprint": "overlapping-document",
    "existing_activity_ids": ["already-imported-event"],
    "new_activity_ids": ["confirmed-additional-event"],
    "reason": "Matched statement rows and confirmed an additional execution"
  }
}
```

Place it inside `metadata.rikdom_import_diagnostics`, alongside its required
version/coverage/unsupported fields. Preview through `normalized-statement-json`.
Existing identities must exist in the declared scope; new identities cannot
overwrite unrelated events. Only the explicitly mapped ambiguity is resolved.
Assigning fresh IDs to every row would duplicate existing transactions.

## Blocking preflight codes

| Code | Meaning |
| --- | --- |
| `INVALID_IMPORT_DIAGNOSTICS` | Malformed or unsupported evidence contract. |
| `AMBIGUOUS_IMPORT_IDENTITY` | Conflicting occurrence identity or unresolved anonymous overlap. |
| `CORRECTION_CONFLICT` | Invalid correction chain, colliding key/ID, immutable-event rewrite, or unsupported dependency. |

Blocked imports and previews do not append run logs or write canonical files.
