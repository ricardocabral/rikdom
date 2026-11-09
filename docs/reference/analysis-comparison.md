# Saved performance comparison

`compare-analysis` compares two recorded answers and their captured evidence. A
consumer can inspect changes after a reviewed correction or newer FX evidence
without reading a live portfolio or executing the recorded environment.

## Supported inputs and interfaces

Both inputs must be complete directories with `analysis-run.json` declaring
`format: rikdom-analysis-run`, `format_version: "1.0"`, and
`operation: performance`. This includes directories restored from v2 analysis
archives. ZIP files, v1 portfolio exports, v3 aggregate captures, omitted/redacted
runs, other operations and unsupported evidence versions are rejected. Use the
existing [capture and restore workflow](../how-to/capture-and-replay-analysis.md)
to obtain complete run directories.

```sh
rikdom compare-analysis --before out/original-run --after out/corrected-run
```

```python
from rikdom.analysis_comparison import compare_analysis_runs
from rikdom.analysis_runs import AnalysisRunError

try:
    comparison = compare_analysis_runs("out/original-run", "out/corrected-run")
except AnalysisRunError as error:
    print(error)
```

The Python function returns a JSON-compatible dictionary. The CLI prints the same
contract to stdout and returns 0 for a valid comparison, including incompatible
or unresolved comparisons. It returns 1 with `Analysis comparison failed: ...` on
stderr for invalid/unavailable evidence, with no success JSON. Python errors use
`AnalysisRunError`, a `ValueError` subclass.

These interfaces only read selected local files. They do not replay calculations,
import statements, run plugins/providers, acquire data, render reports, install an
environment, bootstrap a workspace, or write canonical records or saved runs.
Existing capture, export, restore, replay and performance contracts are unchanged.

## JSON contract version 1.0

The envelope contains `format: rikdom-analysis-comparison`,
`format_version: "1.0"`, `operation: performance`, and `replayed: false`.
Consumers should check these fields and tolerate additional dictionary fields.
Unsupported input contracts fail instead of silently dropping evidence.

| Field | Meaning |
| --- | --- |
| `before`, `after` | Run references, captured scope/dates/currency, creation time, input inventory, result reference, parameters, methods, environment and source/review revisions. |
| `changes` | Changed file references and input roles/mappings; added, removed and modified activities; changed portfolio sections, parameter/method/environment keys; valuation and FX file subsets; whether retained source/review evidence changed. |
| `compatibility` | `comparable` and explicit `reasons`. A valid incompatible comparison still exposes evidence. |
| `coverage` | Before/after valuation/FX status, warnings, retained statement history coverage and unsupported events, recorded attribution status and valuation replay coverage where present; `changed` flag. |
| `deltas` | Supported numerical recorded-answer differences, or an empty object for incompatible summaries. |
| `explanation` | Conservative input-isolation classification, held-fixed checks, and explicit absence of causal proof. |

Each evidence reference has a relative `path`, RFC 6901 JSON `pointer` (empty for
the whole file), and SHA-256 of the **whole verified file**, not just the selected
subtree. Resolve it under that side's `run.directory`. References point only to
captured normalized evidence, never implicitly to external statements or the live
workspace. JSONL file references select the whole journal.

`run.sha256` identifies the exact manifest bytes. `result.sha256` identifies the
recorded result bytes. Each input has its role, copied-file SHA-256 and available
`original_sha256` (before capture rewrote relocatable config paths).
`input_sha256` hashes the canonical JSON representation of the captured `inputs`
mapping and the `files` inventory excluding `result.json`, using sorted keys,
compact separators, UTF-8, non-ASCII characters preserved and a trailing newline.
It does not include parameters; those have separate manifest pointers. Creation
time differences alone do not imply different financial inputs or answers.

`source_reviews` lists existing retained reviewed-import revision fields
(`source_revision`, `source_payload_hash`, `content_hash`, `version`) and decision
fields (`id`, `status`, `source_revision`, `accepted_source_revision`) with pointers
to their full captured records. Activity changes expose identity, source reference,
provenance and existing immutable correction links where present. Other source
and market-observation details remain accessible through exact input/result
pointers, including `fx_evidence`, `valuation_replay`, and
`return_convention_evidence`. Missing revision/provenance fields are null or
absent evidence, not invented history.

## Compatibility and numbers

Numerical comparison supports only the top-level **portfolio** performance
summary. Account, strategic-bucket and instrument captures can be inspected, but
their numerical comparisons are unsupported. Nested calendar rows, benchmarks,
profit decomposition, accounts and instruments have no numerical delta contract.

A comparable summary requires the same known portfolio identity, unchanged
account scope, portfolio selection, requested and resolved date window, reporting
currency, methods and treatment/return semantics. Recorded environments must
match each other and the trusted installed runtime requirements used by replay.
Unknown methods or changed method evidence are explicit incompatibilities.
Foreign runtime evidence is inspected without executing it; even two matching
foreign environments receive `recorded_runtime_unsupported` and no deltas.
Lock/reference and other recorded environment differences are conservatively
reported as incompatible, even where replay does not enforce that field.

`scope.account_ids` lists identities explicitly declared in captured holdings,
activities, snapshot `totals.by_account`, and policy `accounts[].account_id`.
`account_ids_by_evidence` retains each collection's identities separately so an
unchanged policy catalog cannot hide changed observed membership.
`has_unassigned_accounts` preserves missing assignments and the existing
`__unassigned__` marker. No declared identities produces `account_ids: null`;
this is unknown scope, not a verified empty account set. Matching unknown scope
does not prevent comparison of recorded portfolio answers, but does not establish
account coverage. Changed declared membership or assignment evidence suppresses
all numerical deltas with `account_scope_changed`. A hypothetical top-level
portfolio `accounts` field does not establish account scope.

For incompatible summaries `deltas` is `{}`. `compatibility.reasons` identifies
scope, identity, account scope, dates, currency, methods/semantics, unsupported
numerical scope or recorded runtime differences. Before/after scope, dates,
currency, parameters and evidence remain available for explanation.

For compatible summaries these fields can have deltas:

- `start_value_base`, `end_value_base`, `net_external_cashflow_base`, in reporting
  currency units.
- `twr_pct`, `twr_return_pct`, `linked_twr_pct`, `mwr_pct`, in **percentage points**.

Each row has `before`, `after`, `delta`, `unit` and `status`. `delta` is
`after - before` over the recorded JSON numbers, with no new calculation of
performance. A run delta is never an investment return. No percent growth of a
run delta, contribution allocation, FX attribution amount or residual bridge is
computed. Unavailable/missing financial values, incomplete FX/valuation results,
unspecified return conventions for percentage fields, and nonfinite differences
produce `delta: null` and `status: unknown_or_unavailable`, never zero.

The original coverage limits remain visible. A recorded snapshot value remains
`recorded_unverified`; a missing history-coverage assertion remains null.
Comparable recorded numbers do not certify real-world history completeness or
historical valuation FX. A reproduced unavailable answer would still be
unavailable, and comparison does not establish reproduction at all.

## Isolation and unresolved differences

`explanation.causation` is always
`not_established_by_recorded_comparison`. Checksums and differences establish what
was recorded, not why a calculation or real-world outcome changed.

The supported classifications are:

- `unchanged`: input evidence, parameters, methods, environment and recorded
  result are unchanged. Manifest creation times can differ.
- `controlled_source_correction`: exactly one new activity carries a valid
  existing `rikdom_correction` link to an earlier captured activity. Earlier rows
  are preserved, no other portfolio section changes, all other input bytes and
  parameters (including `analysis_as_of`), methods and environment are fixed,
  and the summary is compatible.
- `controlled_fx_revision`: other input bytes, parameters, methods and environment
  are fixed and the summary is compatible. Only the historical FX retrieval cutoff
  changes with the same series; or its series retains all earlier observations
  and appends explicit revisions of observations for mapped FX series, preserving
  series metadata, configuration and effective dates/currencies. A mapping, age
  policy, unrelated series or legacy undated journal change stays unresolved.
- `unresolved`: multiple drivers, multiple independent corrections, reviewed
  overlays/source revisions without the bounded correction pattern, method or
  runtime changes, unexplained output changes, or other unsupported isolation.

`held_fixed` reports the evidence checks. The two controlled classifications
isolate captured input variation only; they do not assert that a recorded output
was calculated correctly or assign a causal amount. A self-consistent edited
result cannot be certified without a separate successful replay. Broad reviewed
import and historical valuation changes remain inspectable but receive no
fabricated causal decomposition.

## Integrity and failures

Every declared file is read into the existing capture reader's verified byte
inventory before comparison. Subsequent processing uses those bytes, not a second
read of mutable live inputs. Size/hash mismatches, missing dependencies, unsafe
paths, omitted evidence, malformed/duplicate-key JSON, torn JSONL, nonfinite
numbers, missing required result/method/environment evidence, inconsistent roles,
and unsupported contracts fail. Captured source/review pointers are validated
where the supported retained contracts supply them. Checksums detect corruption;
they do not authenticate an author or prove source truth. A malicious actor who
rewrites both evidence and hashes is outside that integrity guarantee.

Validation binds supported input roles to their document structures, including
snapshot totals, legacy FX journal rows, and the existing pure flow-valuation
parser. A `linked_subperiod` claim requires a declared, valid, nonempty
`flow_valuations` input. Complete historical FX and valuation claims require
their declared inputs and corresponding recorded evidence; complete valuation
inputs must assert complete positions. Complete profit decomposition requires
captured reviewed basis and complete period history (and complete inventory for
the multicurrency contract). Complete instrument results require the captured
holding's complete-history declaration. Supported nested result containers,
statuses and financial values are checked, including FX evidence, attribution
sections and instrument rows. Errors identify the offending role or field.

These checks establish structural support for recorded claims. They perform no
market lookup, performance calculation, reconciliation or source-truth check.
Unrecognized optional extension fields remain in the referenced captured bytes;
comparison assigns them no supported semantics or numerical deltas.

Failure leaves both run directories and prior valid state intact. The comparison
contains private captured source references and environment metadata; it is not
a redacted sharing format.
