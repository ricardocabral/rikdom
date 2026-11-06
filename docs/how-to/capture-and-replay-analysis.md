# Capture and replay a performance analysis

Capture computes from a private copy of the selected normalized records. Later
source imports or market-cache updates cannot change that saved run. These
commands use installed local calculations and never acquire data or install code.

```sh
rikdom capture-analysis \
  --portfolio data-sample/historical-valuation-replay/portfolio.json \
  --snapshots data-sample/snapshots.jsonl \
  --fx-history data-sample/fx_rates.jsonl \
  --historical-valuations data-sample/historical-valuation-replay/replay.json \
  --historical-fx data-sample/historical-valuation-replay/historical-fx.json \
  --flow-valuations data-sample/historical-valuation-replay/flow-valuations.json \
  --output out/saved-analysis
rikdom export-analysis --run out/saved-analysis --output out/analysis.zip
rikdom verify-export --bundle out/analysis.zip
rikdom restore-analysis --bundle out/analysis.zip --output out/restored-analysis
rikdom replay-analysis --run out/restored-analysis
```

To restore and reproduce the archive in one step, use a fresh destination:

```sh
rikdom replay-export --bundle out/analysis.zip --restore-dir out/reproduced-analysis
```

The command returns `status: reproduced`, `restore_dir`, and the same performance
JSON under `result`. It publishes the directory only after financial equality
passes. Incomplete/redacted archives can be inspected with `restore-analysis`,
but `replay-export` rejects them without publishing a destination.

`capture-analysis` accepts the current `performance` calculation options,
including scope/window, instrument/terminal value, policy/benchmark directory,
historical valuations/FX, flow valuations and profit basis. Supply existing local
files: capture never bootstraps a missing workspace. Default portfolio/snapshot/FX
paths are resolved like `performance`; explicitly selected missing paths fail.
An API caller can omit unused snapshot/FX inputs to capture an explicit empty
journal. Selected required benchmark definitions/files must exist. Unknown
options and unsupported contracts fail instead of being silently discarded.

Capture, restore and replay share the existing performance handler and its JSON
result. Replay verifies a snapshot of every declared file, calculates from those
verified bytes in a temporary directory, and compares the canonical JSON SHA-256
to `result.json`. It prints the same financial output without changing saved
records or writing reports. Existing rounding in the calculation contract applies
(for example percentage fields round to six decimals); replay adds no tolerance
or additional rounding. The complete selected JSON must match, including methods,
annualization, fees/taxes treatment, evidence, calendar rows and warnings. HTML
bytes and report generation timestamps are outside this equality contract.
Reproducing an unavailable result preserves its warnings and unavailable fields;
it does not certify that the underlying history is complete.

The manifest records the FX selection timestamp so future wall-clock dates cannot
select a newer rate from the captured undated history. Dated configs keep their
explicit knowledge cutoff. Exact copied normalized provenance/review decisions
remain evidence even when the live portfolio is subsequently refreshed. No
importer or output plugin executes during calculation replay; the plugin execution
inventory is empty explicitly. Upstream importer identity/version is retained only
when present in normalized provenance. Re-running an importer needs its original
statements and matching environment separately; statements are never implicitly
included.

## Environment and failure diagnostics

The private manifest records installed distribution version, Python module version,
Python major/minor and implementation, OS, installed direct/relevant transitive
dependency versions, core Python/resource-content digest, and available
`pyproject.toml`/`uv.lock` hashes. The current repository's differing distribution
and module versions are recorded separately. Lock references are evidence, not
an automatic environment installer. No code or credentials are bundled.

Replay and complete restore require the recorded runtime/OS, distribution/module,
dependency versions and identical core/resource digest. Python patch versions are
not constrained; exact output equality remains required. A later source edit can
therefore be incompatible even when its package version is unchanged. Obtain the
recorded trusted release/environment separately. There is no force-success mode.

- **Missing:** restore/replay names the absent input or nested cache.
- **Changed:** size/hash mismatch refuses calculation; output mismatch refuses reproduction.
- **Incompatible:** environment diagnostics name the mismatching evidence category.
- **Omitted:** incomplete exports remain readable evidence and cannot replay.

Archive checksums detect corruption, not authorship. Exports are unencrypted local
files. Run them with trusted installed code and apply normal OS/disk protection.
The access inventory documents this boundary; it does not sandbox installed code.

## Review exports before sharing

```sh
rikdom export-analysis --run out/saved-analysis --output out/private.zip --dry-run
rikdom export-analysis --run out/saved-analysis --output out/share.zip --redacted --dry-run
rikdom export-analysis --run out/saved-analysis --output out/share.zip --redacted
```

The preview shows the exact manifest/file inventory without writing. A full export
contains private normalized portfolio evidence and results. Redaction removes all
normalized inputs, parameters, financial results and source references, retaining
only environment and method metadata. It is intentionally non-replayable. Review
the preview before distributing it; environment metadata can still identify a
software setup. Diagnostics print input roles rather than record contents.

For a provider restriction, omit its role explicitly while retaining the expected
hash and reason:

```sh
rikdom export-analysis --run out/saved-analysis --output out/restricted.zip \
  --omit-input historical_fx.market_series_file --omission-reason license --dry-run
```

Repeat `--omit-input` for additional roles shown in the preview. A selective
omission preserves other private data, so it is not the same as `--redacted`.
Both forms set `replayable: false`; restoration can inspect the evidence but
`replay-analysis` reports the omission and fails without fetching replacements.
