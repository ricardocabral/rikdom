# Measure independent completion of the core workflow

Use this voluntary, local protocol to measure first-real-statement → review →
portfolio answer/report completion for [issue #45](https://github.com/ricardocabral/rikdom/issues/45).
No measured sample is currently available: sample size and observation window
are unavailable. The proposed **under-15-minute target is unvalidated**; synthetic
fixtures and tutorial time estimates are not evidence of independent completion.

## 1. Prepare a private measurement note

Participation and sharing are optional. Work only with your own local statement;
this protocol does not request uploads, telemetry, accounts, or personal
onboarding. Keep statements, portfolio files, reports, and detailed notes local.
If you want a rehearsal, use the [synthetic tutorial](../tutorials/first-portfolio.md)
and label it synthetic; exclude it from real-statement completion results.

Use a text note or copy the [blank synthetic notebook](../../data-sample/workflow-measurements/example.json)
from the repository root into a private temporary directory:

```sh
measurement_dir="$(mktemp -d)"
cp data-sample/workflow-measurements/example.json "$measurement_dir/measurement.json"
python3 -m json.tool "$measurement_dir/measurement.json" > /dev/null
printf '%s\n' "$measurement_dir/measurement.json"
```

The JSON is an optional note template, not a Rikdom input or core schema. Its
empty `attempts` list and null measurements are not a completed pilot. Copy
`attempt_template` into `attempts` for each actual run, fill it in, and change
`synthetic_only` only when recording actual observations. Never edit or commit
private measurements in the tracked example. Choose a local deletion date, such
as after the next statement comparison; choose a durable private location if
temporary storage may disappear before then. Delete only measurement copies,
not canonical portfolio records. Local-only participation needs no consent form;
any later sharing needs your explicit choice and a preview of the exact summary.

## 2. Fix the task and clocks before starting

Write down the observation-window start/end (with timezone), Rikdom commit or
version, OS, importer/version, prior experience, and any prior rehearsal. Choose
one statement/account scope, statement date range, reporting currency, and a
specific supported question. For example: “What gross income was recorded in
this period, in each native currency, and what remains unknown?” Use the
[income guide](summarize-income.md) to check its supported meaning. For a report,
choose the required figures and evidence before running it; rendering HTML alone
is not completion. Record required calculation methods and tolerances in advance.

Record installation separately: start before obtaining/installing Rikdom and
required importer/report tools, stop when they are ready, and note elapsed time,
failures, downloads, and already-installed dependencies. Record equivalent setup
for the baseline. Do not hide task-specific preparation in installation: locating
the importer instructions, creating the portfolio workspace, statement conversion,
mapping, configuration, and review belong in workflow time. Start with a separate
workspace for your own records; do not seed it with the tutorial's sample assets.

Start the workflow clock with installation ready and the first real statement
already downloaded locally, before opening task instructions or preparing the
workspace. Record statement acquisition effort separately for both workflows.
Stop at completion or when you stop trying. Include documentation reading,
errors, retries, waits, review, and corrections in wall-clock elapsed time.
Record interruption time/reason separately; report raw elapsed time even if you
also report active time. Pick a stopping budget before starting; 15 minutes is
a hypothesis, not a forced cutoff. Never count stopping at that point as success.

## 3. Attempt the workflow without personal onboarding

With the workflow clock running, run the following from the repository root.
Choose the identity, display name, owner kind, and three-letter reporting currency
for your portfolio; the values below are editable examples. Keep this shell's
path variables for every subsequent command. A temporary workspace is suitable
for a rehearsal; move real records to durable private storage before follow-up.

```sh
workspace="$(mktemp -d)"
data_dir="$workspace/data"
out_root="$workspace/out"
portfolio="$data_dir/portfolio.json"
mkdir -p "$data_dir" "$out_root"
portfolio_id="my-local-portfolio"
display_name="My portfolio"
owner_kind="person"
reporting_currency="USD"
python3 - "$portfolio" "$portfolio_id" "$display_name" "$owner_kind" "$reporting_currency" <<'PY'
import json
import sys
from pathlib import Path

path, portfolio_id, display_name, owner_kind, currency = sys.argv[1:]
reference = json.loads(Path("data-sample/portfolio.json").read_text())
empty = {key: reference[key] for key in (
    "schema_version", "schema_uri", "asset_type_catalog"
)}
empty.update(
    profile={"portfolio_id": portfolio_id, "owner_kind": owner_kind,
             "display_name": display_name},
    settings={"base_currency": currency},
    holdings=[], activities=[],
)
with Path(path).open("x") as target:
    json.dump(empty, target, indent=2)
    target.write("\n")
for name in ("snapshots.jsonl", "fx_rates.jsonl"):
    with Path(path).with_name(name).open("x"):
        pass
PY
uv run --offline --no-sync rikdom validate \
  --portfolio "$portfolio" --data-dir "$data_dir" --out-root "$out_root"
```

This reuses only the existing schema identifiers and asset **type definitions**.
It copies no demo holdings, balances, accounts, activities, history, FX observations,
or source coverage. Empty history/FX files assert no observations. Keep these files
in place: some commands bootstrap missing workspace files from samples. Do not use
`make bootstrap` or `workspace init` with sample seeding for this run. Validation
of the empty structure does not establish statement coverage.

1. Follow [import a broker statement](import-a-statement.md) and the chosen
   importer's README. Preview, inspect source scope/coverage and mappings, then
   explicitly accept the import. Record any format conversion or manual work.
   An unsupported input is a failed attempt with an importer limitation, not an
   omitted case. Do not build an importer as part of a timed completion run.

   Set `importer` and `statement` to the selected plugin and absolute local input
   path (after any required conversion), then preview and, after review, accept:

   ```sh
   importer="csv-generic"
   statement="/absolute/private/path/to/statement.csv"
   uv run --offline --no-sync rikdom import-statement \
     --plugin "$importer" --plugins-dir plugins --input "$statement" \
     --portfolio "$portfolio" --data-dir "$data_dir" --out-root "$out_root" \
     --fx-history "$data_dir/fx_rates.jsonl" --dry-run
   # Run only after inspecting and accepting the preview:
   uv run --offline --no-sync rikdom import-statement \
     --plugin "$importer" --plugins-dir plugins --input "$statement" \
     --portfolio "$portfolio" --data-dir "$data_dir" --out-root "$out_root" \
     --fx-history "$data_dir/fx_rates.jsonl" --write --reconcile
   ```

2. Validate and read the generated reconciliation/trust evidence. Check against
   the local statement; record mismatches, missing coverage, and unavailable
   comparisons. Apply only corrections you can support; use
   [reviewed imports](../reference/reviewed-imports.md) when applicable. Zero
   warnings does not establish completeness. Record what you reviewed even if
   no discrepancy was found.

   ```sh
   uv run --offline --no-sync rikdom validate \
     --portfolio "$portfolio" --data-dir "$data_dir" --out-root "$out_root"
   ```

   Inspect `$out_root/reports/reconciliation.md` and
   `$out_root/reports/holding_trust.md` against your statement.

3. Produce the chosen [answer](summarize-income.md) or
   [report](render-a-report.md). Verify its scope, dates, currency, method, and
   evidence against the question. State remaining unknowns beside the answer.
   Save local evidence references for your own check; do not put them in a
   shared summary.

   For the received-income question, choose the actual inclusive statement dates:

   ```sh
   start_date="2026-01-01"
   end_date="2026-12-31"
   uv run --offline --no-sync rikdom income \
     --portfolio "$portfolio" --data-dir "$data_dir" --out-root "$out_root" \
     --out-dir "$out_root/reports" --start "$start_date" --end "$end_date"
   ```

   Read `$out_root/reports/income.json` and `income.md`, including diagnostics;
   totals remain in native currencies. If HTML was the predeclared output, use:

   ```sh
   RIKDOM_DISABLE_QUARTO=1 uv run --offline --no-sync rikdom viz \
     --portfolio "$portfolio" --data-dir "$data_dir" --out-root "$out_root" \
     --snapshots "$data_dir/snapshots.jsonl" --fx-history "$data_dir/fx_rates.jsonl" \
     --plugins-dir plugins --out "$out_root/dashboard.html" --include-current
   ```

   Open `$out_root/dashboard.html` and `$out_root/portfolio-report.html`. This
   explicitly selects fallback HTML; `--include-current` adds a derived current
   view for rendering, not historical source evidence. Missing FX/history and
   unavailable required figures remain limitations; do not fill them with samples.

Mark **attempted** when the workflow clock starts. Mark **completed** only when
import acceptance, review, and the predeclared answer/report checks all finish.
An explicit limitation can satisfy a question about coverage; an unavailable
required figure cannot satisfy a question requiring that figure. Record every
unresolved discrepancy even in a completed run. Mark **failed** when you stop
without meeting the checks, including errors, abandonment, unsupported input,
or the stopping budget. A run still in progress remains attempted with outcome
`in_progress` at the window cutoff; do not quietly drop it.

Record elapsed seconds, outcome, failed stage/reason, retries, manual steps,
and assistance for every attempt, including failures. Public documentation is
allowed. Personal walkthroughs or task-specific human/AI help make the run
assisted: retain its outcome, but exclude it from independent-completion and
under-15-minute success counts. Record discrepancies separately as found,
resolved with evidence, unresolved, or not assessable; missing coverage is not a
confirmed discrepancy and an unperformed check is not zero discrepancies.

## 4. Compare a matched existing workflow

Before claiming less effort or better reconciliation, attempt the same task in
your existing spreadsheet, broker export process, or other local workflow. Use
the same user, statement revision, account/date scope, currencies, question,
required outputs, methods, tolerances, and stopping rule. Record baseline tool
version, setup, starting state (including saved mappings), and steps. Keep separate
copies so one run's corrections do not silently supply the other's answers.
Record order and prior familiarity; where several volunteers independently
participate, vary order and disclose it. If you already know the answer, record
that learning effect. Do not claim a controlled comparison from an unmatched run.

Use the same timing and outcome rules for both tools. Keep successes, failures,
in-progress attempts, manual reconciliation, unavailable checks, and unresolved
discrepancies. Pair attempts with a local ID. Compare elapsed time for matched
completed pairs while separately reporting all attempted pairs and their outcome
combinations; a failed task is not a quick success. Compare discrepancy resolution
only over the same assessable checks, with evidence for each claimed resolution.
If scope/methods cannot match, report the difference and withhold comparative
effort/reconciliation claims. A small voluntary sample describes those attempts;
it does not establish a general improvement or a cause.

## 5. Repeat at the next statement update

Choose a follow-up window before closing the first run, based on the expected
next statement date. When that statement becomes available, repeat import,
review, and the same question using the saved workspace and reviewed decisions.
Record elapsed time, failures, changed facts, preserved/conflicting reviews,
unresolved discrepancies, and whether the answer/report can be updated. Repeat
the baseline too if making a repeat-effort claim. Reimporting the unchanged first
statement tests idempotency, not repeat use after an update.

Keep one first attempt per user for the first-completion/15-minute verdict;
report retries separately rather than replacing that first outcome.
At cutoff, distinguish update available and attempted, available but not attempted,
not yet available, and follow-up unknown. A later retry is another linked attempt;
it does not erase an initial failure. No update or missing follow-up is not proof
of retention or abandonment. Follow-up is self-recorded; no recruitment or contact
is needed to use this protocol.

## 6. Report only what the observations support

Put the sample size and exact observation window **beside every verdict**,
including first completion, timing, discrepancies, comparison, and repeat use.
State the local note/output source, selection/filter and read date behind each
count. Use a short summary with these fields; leave unknown values unavailable:

| Verdict | Evidence to include alongside it |
| --- | --- |
| First completion | Independent users; attempted/completed/failed/in-progress runs; assisted and synthetic runs separately; window. |
| Under 15 minutes | Independent first attempts completed with raw elapsed <900 seconds / all independent first attempts; missing timings; elapsed distribution for completed and failed runs separately; installation separately; window and user count. |
| Discrepancies | Assessed cases/checks, found/resolved/unresolved/not-assessable counts and resolution evidence; window and user/attempt counts. |
| Comparison | All matched attempted pairs and success/failure combinations; completed-pair time differences; comparable checks and unresolved differences; excluded/unmatched cases with reasons; window and user count. |
| Repeat use | First-run users, users with an update available, subsequent attempts/completions/failures, no-attempt/not-due/unknown follow-up; update window and timing/discrepancies. |

Do not turn missing observations into zero or infer success from an empty log.
Until measured notes exist, report “unavailable: no measured sample; sample size
and observation window unavailable; under-15-minute target unvalidated.” If you
voluntarily share a summary, remove statements, balances, identifiers, file paths,
source pointers, raw logs, and revealing free text. Share only the previewed
summary; choose its retention/deletion terms before sharing. A public issue may
retain copies, so local-only notes are sufficient.

Use reproducible observed failures to choose small fixes to records, validation,
shared calculations, or read contracts. Route UI/report design, provider support,
strategy advice, and hosted operation to the owners in
[product scope](../explanation/product-scope.md#where-additional-value-belongs).
Use synthetic reproductions in bug reports; label a suspected cause unproven until
a check isolates it. This protocol adds no runtime or data-collection service.
