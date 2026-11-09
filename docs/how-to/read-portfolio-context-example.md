# Read captured portfolio context with an external script

Use [`scripts/read_portfolio_context.py`](../../scripts/read_portfolio_context.py)
to consume one existing **captured performance run**. This educational example
runs locally without an LLM, server, provider, credentials or new dependencies.
It demonstrates existing contracts; its output wrapper is not a new stable core
API or a general portfolio context schema.

## Capture and read a synthetic example

From a checkout with Rikdom's dependencies installed, capture the tracked
synthetic sample into a new directory:

```sh
uv run rikdom capture-analysis \
  --portfolio data-sample/historical-valuation-replay/portfolio.json \
  --snapshots data-sample/snapshots.jsonl \
  --fx-history data-sample/fx_rates.jsonl \
  --historical-valuations data-sample/historical-valuation-replay/replay.json \
  --historical-fx data-sample/historical-valuation-replay/historical-fx.json \
  --flow-valuations data-sample/historical-valuation-replay/flow-valuations.json \
  --by portfolio --output out/context-example
```

Allocate disposable scratch space **outside canonical data and all saved runs**,
then read the capture:

```sh
scratch=$(mktemp -d)
trap 'rmdir "$scratch"' EXIT
uv run python scripts/read_portfolio_context.py \
  --run out/context-example --scope portfolio --scratch-dir "$scratch"
```

The script removes its private scratch directory and core replay removes its
own OS temporary directory, on success or failure. The command above removes
the empty caller-created parent when the shell exits. Core replay also uses the
OS temporary directory: keep `TMPDIR` outside canonical data and saved runs.
The reader rejects scratch locations inside the selected run. It cannot discover
all canonical directories on your machine; selecting the disposable location is
the caller's responsibility. It neither modifies the run nor reads the original
workspace, requests network access, installs environments, or runs plugins.
These are behavior contracts for trusted installed Python, not an OS sandbox.

`--scope portfolio` is required. The capture must also have `parameters.by` set
to `portfolio`. Account, strategic-bucket and instrument selection are unsupported
and fail rather than relabeling portfolio totals. ZIP exports and aggregate runs
are not accepted. To use a v2 performance ZIP, first restore it with the existing
[`restore-analysis` workflow](capture-and-replay-analysis.md).

## Interpret the evidence before using values

The output contains:

- `scope`: the explicitly selected portfolio scope.
- `capture.manifest`: the source manifest path and SHA-256 of the bytes read.
- `capture.files`: every captured input, nested price/FX cache, benchmark file
  when present, and expected result, with source paths, byte counts, roles and
  SHA-256 hashes. `original_sha256`, when present, describes the pre-portability
  input; `sha256` identifies the captured file actually used.
- `capture.parameters`, `inputs`, `methods`, `environment`, `created_at`, and
  format/operation versions: the recorded calculation selection and requirements.
- `result`: the **unmodified** result from `replay_analysis_run`. Currency,
  actual period bounds, evidence, methods, coverage, diagnostics, warnings and
  null fields retain the [performance output contract](../reference/performance-output.md).
- `limitations`: reminders about the boundaries of reproduction and evidence.

The reader snapshots the manifest and each declared file once into disposable
scratch, strictly parses JSON/JSONL, and calls the existing replay API on that
copy. Replay validates sizes/hashes, environment and calculation equality; the
reader also checks captured method labels against the reproduced result before
anything is printed. An input change during copying either still matches the
captured hashes or fails verification. A later source change cannot change the
snapshot's calculation or citations. Citation paths identify where bytes were
read; the hashes identify those bytes even if the path subsequently changes.
This does not promise an atomic snapshot of a changing live workspace.

Use `result.base_currency`, `period_start` and `period_end` as the result's actual
currency/window. Requested `since`/`until`, capture `created_at`, the FX selection
`analysis_as_of`, and observations' `effective_at`/`retrieved_at` have different
meanings. Capture time does not make an old price current. Follow the nested
valuation/FX observation evidence for freshness and knowledge cutoffs.

Read the selected `twr_return_pct` together with `twr_method` and
`twr_fallback_reason`; the legacy `twr_pct` is a Dietz approximation. XIRR MWR is
annualized, while TWR covers the selected period. A complete valuation, residual
bridge or reproduced calculation does not certify global transaction coverage,
resolve disputed source facts, or prove current holdings. Preserve a dispute in
its source/review evidence, cite that captured input, and describe it as unresolved;
this reader does not adjudicate it. Missing, stale, disputed or unavailable values
must never be converted to zero or presented as confirmed absence.

## Exercise complete, approximate and unavailable states

The focused behavioral tests create only synthetic temporary inputs and use real
core capture/replay calculations:

```sh
uv run python -m unittest tests.test_read_portfolio_context -v
```

| State | Synthetic evidence and expected behavior |
| --- | --- |
| Complete selected valuation | The command above values opening positions at BRL 135 and closing positions at BRL 254, with BRL 72 external funding; linked period return is 34.814815%. Raw component coverage remains visible. |
| Approximate return | USD snapshots of 100 and 165 with a midpoint contribution of 50, without before/after flow NAV, produce Modified Dietz 12%, with the fallback reason and warnings retained. |
| Missing or stale prices | Removing eligible prices or aging them beyond the declared maximum makes historical valuations and returns unavailable/null, with missing/stale evidence retained. Recorded snapshot totals are not substituted. |

Tests also block socket connections, compare source/run bytes before and after
reading, check scratch cleanup, and exercise scope mismatches, absent inputs,
malformed or duplicate-key/nonfinite JSON, torn JSONL, tampered hashes/results,
incompatible environments and unsupported formats. A self-consistent edited
result still fails unless the real calculation reproduces it.

## Failures and compatibility

Exit `0` means the captured calculation reproduced, including any unavailable
financial fields. Handled evidence, I/O, compatibility and replay failures return
`1` with stderr and no context on stdout. Missing/invalid command arguments return
`2`. These follow the [CLI conventions](../reference/cli.md#captured-analysis-runs).

Replay requires the recorded Python major/minor and implementation, OS,
distribution/module versions, dependency versions and identical core/resource
content digest. Python patch versions are not constrained; exact canonical JSON
result equality is still required. Even a source edit without a package version
change can invalidate replay. Lock hashes are evidence, not an installer. Obtain
the trusted matching environment separately; this reader has no override or
fallback. See [capture/replay limitations](capture-and-replay-analysis.md#environment-and-failure-diagnostics).

Checksums detect inconsistency, not authorship or a malicious replacement of an
entire run. Output includes financial results, local paths and captured environment
metadata; review it before sharing. Proposals to correct records or change policy
belong in separately reviewed, validated write workflows.
