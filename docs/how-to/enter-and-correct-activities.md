# Enter and correct activities

Use normalized JSON for a manually verified event. Bootstrap a workspace first;
preview commands do not create a missing workspace.

## Enter an event

Save this as `manual.json`, replacing the holding/account IDs with your own:

```json
{
  "provider": "manual",
  "generated_at": "2026-10-26T12:00:00Z",
  "activities": [{
    "id": "manual-buy-001",
    "idempotency_key": "manual-buy-001",
    "event_type": "buy",
    "status": "posted",
    "effective_at": "2026-10-20T12:00:00Z",
    "holding_id": "my-holding",
    "account_id": "my-account",
    "quantity": 2,
    "money": {"amount": 100, "currency": "EUR"},
    "source_ref": "manual-note-001"
  }]
}
```

Preview, then apply:

```bash
uv run rikdom import-statement --plugin normalized-statement-json \
  --input manual.json --data-dir data --out-root out --dry-run
uv run rikdom import-statement --plugin normalized-statement-json \
  --input manual.json --data-dir data --out-root out --write --reconcile
```

Keep IDs and keys stable when repeating an import. A changed event with the same
identity is an update under ordinary source-import semantics; use the correction
workflow below when the original must remain in the ledger. Entry does not
revalue holdings, create tax lots, or rewrite snapshots automatically.

## Correct an existing event

Create `replacement.json` with a complete replacement activity, a new ID, and
the corrected fields. For the example above:

```json
{
  "id": "manual-buy-001-correction-1",
  "event_type": "buy",
  "status": "posted",
  "effective_at": "2026-10-20T12:00:00Z",
  "holding_id": "my-holding",
  "account_id": "my-account",
  "quantity": 3,
  "money": {"amount": 150, "currency": "EUR"}
}
```

```bash
uv run rikdom activity correct manual-buy-001 --input replacement.json \
  --reason "Quantity and consideration verified against source" --data-dir data
uv run rikdom activity correct manual-buy-001 --input replacement.json \
  --reason "Quantity and consideration verified against source" --data-dir data \
  --write --reconcile
```

The command generates a stable correction key when omitted. Do not copy the
original's idempotency key. A supplied key colliding with another event is rejected.
Preview shows the transition to portfolio schema `2.0.0`; the write records the
new contract and replacement together in one atomic portfolio update. The original
event remains unchanged. Calculations select the latest replacement once.

Repeat the same command for a no-op. For a later correction, target the current
replacement ID. Replaying an earlier exact correction also remains a no-op after
a newer correction. Conflicting replays, forks, cycles, and missing targets fail.
For cancellation, use a complete linked replacement with `status: "cancelled"`.

Apply one new correction at a time. Corrections involving tax-lot dependencies
or corporate actions require separate review and are rejected by this workflow;
Rikdom does not rebuild dependent lots. Existing snapshots retain their original
observations.

Correction-bearing data requires a correction-aware reader. Older software that
ignores schema versions can double-count the stored events. Preserve the raw audit
ledger when exporting; do not downgrade it for an older calculator.

## Declare the evidence for a quantity comparison

An importer cannot infer complete history from the first transaction it sees.
When you have verified that the initial quantity was zero and all quantity events
are present, a normalized statement may supply:

```json
{
  "metadata": {
    "rikdom_import_diagnostics": {
      "version": 1,
      "document_fingerprint": "your-stable-document-reference",
      "history_coverage": [{
        "scope": "your-opaque-account-scope",
        "account_id": "my-account",
        "holding_id": "my-holding",
        "status": "complete",
        "event_types": ["buy", "sell", "transfer_in", "transfer_out", "split", "merger"],
        "from": "2026-01-01",
        "through": "2026-10-26",
        "timezone": "Europe/Paris",
        "history_origin": "inception",
        "opening_quantity": 0,
        "position_basis": "trade",
        "effective_at_basis": "trade",
        "evidence": {"kind": "user_declaration", "source_ref": "reviewed-source-note"}
      }],
      "unsupported_events": []
    }
  }
}
```

This is a metadata fragment: place it in a valid normalized statement containing
the existing holding with its stable ID, required fields, explicit `account_id`,
and actual timestamped `as_of`. Preview and write through the normalized importer.
Use source evidence for the date and accounting basis; never substitute import
time. Coverage dates include the whole local calendar day and must reach the
position timestamp. Equivalent `effective_at` timing must be declared explicitly.

The first supported comparison is trade-basis, zero-opening history. Settled or
unknown basis, missing scope/date/timezone, nonzero opening positions, unsupported
movements, and contradictory pre-inception events produce `not_computable`.
No findings does not establish complete history.

See [calculation trust](../explanation/calculation-trust.md) for totals and
[import diagnostics](../reference/import-diagnostics.md) for identity recovery.
