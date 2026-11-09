# Use portfolio context in an external agent

Use this procedure to answer a portfolio question with identifiable local inputs,
supported calculations and explicit limits. It requires an installed Rikdom and
existing local files. The commands below use only tracked synthetic samples;
replace them with an authorized scope for actual use. No model or service is
required. The [read contract](../reference/agent-read-contract.md) defines the
evidence, version and status meanings.

## 1. Select the question and scope

Record the selected workspace/registered portfolio, resolved input paths,
requested accounts or holdings, reporting currency and requested period. With
workspace mode, use `--data-dir` and, when needed, `--portfolio-name`/`--registry`;
with explicit paths, ensure every input belongs to the intended portfolio.
For strict read-only consumption, require inputs to exist and use explicit paths:
some ordinary commands can seed missing default workspace files from tracked
samples. `capture-analysis` does not bootstrap missing inputs.

Read `settings.base_currency`, portfolio `schema_version` and any selected policy's
independent `schema_version`, identity and relevant guardrails. Keep native
currencies visible. A provider account string is not a verified policy account
binding; retain `__unassigned__` and other unallocated evidence.

Choose the supported result for the question:

- Current holdings value/allocation: `aggregate`, including its warnings and
  exclusions; use reconciliation/Python trust records when coverage matters.
- Portfolio return: `performance` over selected snapshot bookends, optionally
  with explicit flow valuations, historical FX/valuations and reviewed profit basis.
- Account return: `performance --by account`, then select the account row and
  retain top-level diagnostics. The top-level return is still portfolio-wide.
- Instrument return: `performance --by instrument --instrument <holding-id>` in
  native currency, subject to its independent history and terminal-value gates.

See [performance output](../reference/performance-output.md) for bucket scope,
method selection and options that support portfolio scope only. Do not construct
an account return by dividing its current value by a portfolio bookend.

## 2. Capture the selected inputs

Stop/co-ordinate imports, corrections, policy edits and cache refreshes while
selecting the input set, or use a separately established consistent copy. Capture
copies files sequentially, including nested dependencies; it is not an atomic
snapshot of a changing live workspace. If concurrent changes cannot be excluded,
state that limitation and recapture from a consistent set. Atomic publication of
the saved run does not remove that limitation.

This synthetic example captures explicit historical valuation, dated FX and
flow-boundary evidence. Choose a new output directory each time:

```sh
rikdom capture-analysis \
  --portfolio data-sample/historical-valuation-replay/portfolio.json \
  --snapshots data-sample/snapshots.jsonl \
  --fx-history data-sample/fx_rates.jsonl \
  --historical-valuations data-sample/historical-valuation-replay/replay.json \
  --historical-fx data-sample/historical-valuation-replay/historical-fx.json \
  --flow-valuations data-sample/historical-valuation-replay/flow-valuations.json \
  --output out/agent-context
rikdom replay-analysis --run out/agent-context
```

Read `out/agent-context/analysis-run.json`, its `inputs`/`files` inventory and
`result.json`. Cite the captured portfolio, not a newer `data/portfolio.json`.
Include `--policy` and the selected `--benchmarks-dir` if the question uses policy
or benchmarks; only referenced benchmark leaves are captured. Include optional
profit basis/other sidecars explicitly. Import logs, original statements and
arbitrary external sidecars are not automatically collected.

For current aggregate evidence, use the separate bundle route:

```sh
rikdom aggregate --portfolio data-sample/portfolio.json \
  --fx-history data-sample/fx_rates.jsonl --bundle out/agent-aggregate.zip
rikdom verify-export --bundle out/agent-aggregate.zip
rikdom replay-export --bundle out/agent-aggregate.zip \
  --restore-dir out/agent-aggregate-restored
```

This captures the actual in-memory portfolio and FX lock with the result. It
does not capture historical return inputs or the policy. Read the restored
`analysis/run.json`, `data/portfolio.json` and `analysis/result.json` together.
The outer version is `3.0.0` and inner run version is `1.0.0`; the performance
directory above has inner version `1.0` and exports through `export-analysis` as
outer version `2.0.0`. Use the corresponding reader, never one assumed shape.

Replay checks the recorded environment as well as evidence and result equality.
It does not install dependencies, fetch missing inputs or reconstruct importers.
Keep an unavailable result and its evidence rather than fetching substitutes
silently. See [capture and replay](capture-and-replay-analysis.md) for portable
performance exports, omissions and environment diagnostics.

## 3. Inspect evidence and limits before answering

For each claim, collect the captured file/hash or retained review revision,
entity IDs, source references and relevant policy section. In reviewed imports,
separate original `source`, accepted-source observations, review decisions and
`effective` projections. A review's evidence may be a user declaration rather
than a provider assertion. Hashes identify the evidence read; they do not certify
authenticity, schema validity or complete history.

Read the result's actual `period_start`/`period_end`, currency, method and return
basis. Report effective observation dates separately from ingestion/retrieval
times and run creation/calculation context. For market revisions, retain both
`effective_at` and `retrieved_at`, the selected cutoff and superseded provenance.
Never substitute capture time for the age of a valuation.

Interpret statuses per field, using the [status mapping](../reference/agent-read-contract.md#completeness-and-uncertainty):

- A complete cashflow FX result or arithmetic growth bridge is complete only
  within its stated scope. It does not establish full real-world portfolio history.
- A Modified Dietz or legacy FX result stays approximate. Include fallback
  reasons and warnings beside the number.
- A missing/stale lookup, unsupported event, unknown coverage, unavailable
  return or disputed review remains visible. Do not replace it with zero, remove
  the source evidence or invent an overall status enum.

Check nulls, warnings, diagnostics, exclusions and scope even after exit zero or
`status: reproduced`. Existing legacy zero placeholders and absent-account-key
conventions must not be described as confirmed zero balances. A read failure or
empty/wrong scope is a failed read, not evidence that there are no holdings.

For a separate read-only consumer, see
[`scripts/read_portfolio_context.py`](../../scripts/read_portfolio_context.py)
and its [example guide](read-portfolio-context-example.md). That guide owns the
example's invocation and output; it does not replace the underlying contracts.

## 4. Present an auditable answer

Keep the answer small enough to inspect. Include:

1. The question, portfolio/account/holding selection, reporting currency and
   actual calculation window.
2. The result, named method and basis, with its qualifications beside it.
3. The captured run/bundle identity, input and result hashes, document/run/method
   versions separately, and read/calculation time where available.
4. Evidence pointers: source document/page or observation, entity IDs, accepted
   review decision/version, and policy section as applicable.
5. Missing, stale, unsupported or disputed evidence, affected conclusions and
   what evidence would resolve them. State sample/record counts for the selected
   evidence rather than implying broader coverage.

For example: “The captured portfolio's supplied bookends reconcile to a residual
of X BRL over [actual window], using `residual_growth`. This is arithmetic over
the supplied valuations and flows; it does not independently verify history,
snapshot FX or lot gains. Evidence: [run/path + hash], [input paths + hashes],
[bookend timestamps and activity IDs].” Fill placeholders from the selected
result; do not present this template as an observed result.

## 5. Keep proposed changes separate

Describe corrections or policy changes as proposals with target IDs/fields,
current evidence identity, proposed values, reasons and source/user evidence.
Do not modify captured inputs or canonical files as a side effect of explanation.

Route an accepted proposal through the existing validation path:

- Preview normalized imports or `import-statement --review-file`; resolve source
  contradictions using the exact preview revision before an authorized write.
- Preview `activity correct` with a complete replacement and reason; preserve
  originals and respect unsupported dependency restrictions.
- Review policy intent with the user, preserve unrelated policy fields and
  validate the candidate with `rikdom.policy.validate_policy`. Before saving an
  authorized policy edit, also run the cross-file check against the selected
  portfolio (replace the placeholders with existing input paths):

  ```sh
  rikdom validate --portfolio <selected> --policy <candidate>
  ```

  Require no policy validation errors and a successful CLI exit; stop on errors
  or unreadable inputs and inspect warnings before saving. The CLI does not
  replace `validate_policy` and skips account checks for a missing/empty catalog.
  If the portfolio has account references, require a candidate catalog resolving
  every reference, including after account renames or removals; exit zero with
  no catalog is not safe acceptance. Schema migration alone does not approve
  new intent.

See [reviewed imports](../reference/reviewed-imports.md),
[entry and correction](enter-and-correct-activities.md) and the
[write boundaries](../reference/agent-read-contract.md#calculation-and-write-boundaries).
After acceptance, calculate and capture a new result. Changed facts, policy,
FX vintage, scope or method are possible causes of changed results; a difference
between captures is not by itself an investment return.
