# Rikdom Roadmap

Make local portfolio records a dependable reference for users, scripts, and
external LLMs. Keep the core small and stable: durable facts, declared intent,
validation, and deterministic financial meaning.

This roadmap contains remaining core work. Priorities express delivery order,
not release dates. Ownership rules and opportunities for independent projects
are defined in [product scope](docs/explanation/product-scope.md).

## Core constraints

- Keep canonical records in readable local JSON/JSONL with explicit schema
  versions, provenance, and compatible evolution.
- Keep reference workflows free and usable offline after installation, without
  mandatory accounts, subscriptions, telemetry, or AI services.
- Separate source observations, reviewed decisions, user policy, derived results,
  and proposed actions. Preserve evidence and disclose uncertainty.
- Keep deterministic calculations reusable by CLI, reports, and external agents.
  Supported calculations retain their documented contracts and coverage limits.
- Keep provider operations and regional rules in extensions. Connections remain
  explicit and optional; cached/file inputs support offline work.
- Keep runtime plugins explicitly trusted. Own validated writes, integrity,
  redacted diagnostics, and recoverable failures; delegate credential storage,
  encryption, scheduling, and isolation to adapters or external tools.
- Add core interfaces only for a demonstrated records, validation, or calculation
  need. An extension's existence does not require a matching core hook.

## Delivery order

| Priority | Outcome | Boundary |
| --- | --- | --- |
| Now, P1 | Answer recurring personal portfolio questions with evidence | Repeat existing workflows after statement updates; close bounded, observed core gaps. |
| Consumer-driven, P1 | Extend explanation and export of saved-run differences | Expand formats or controlled-change attribution for a concrete consumer; preserve evidence and comparability limits. |
| Optional expansion | Research independent use | Test onboarding, matched baselines, and repeat adoption when independent participants are available; this is not a gate for personal-use progress. |

Reliable external-agent reads are documented in the [read contract](docs/reference/agent-read-contract.md),
[context workflow](docs/how-to/use-portfolio-context.md), and [offline reader example](docs/how-to/read-portfolio-context-example.md).
They do not depend on run comparisons, a new protocol, report rendering, or
reconstruction of an importer environment.

## Explain differences between saved runs

[Saved performance-run comparison](docs/reference/analysis-comparison.md) supplies
versioned CLI/Python reads, exact input/result references, source/review and coverage
evidence, compatibility gates and bounded correction/FX isolation. It compares
recorded answers without replaying them or claiming investment performance.

Remaining comparison and [export](docs/reference/export-format.md) work needs a
concrete supported consumer:

- [ ] Extend comparison beyond captured v2 performance directories or portfolio
  numerical summaries when required, retaining each format's scope, dates,
  currency, method, equality and compatibility limits.
- [ ] Isolate controlled method changes or richer reviewed-source changes beyond
  the documented correction/FX cases. Keep incompatible methods, multiple drivers
  and unexplained residuals unresolved; changed recorded facts are not returns.

## Repeat personal portfolio questions

Rikdom is currently used personally by its experienced owner with AI assistance;
there are no independent users. The primary progress signal is whether recurring
portfolio questions can be answered from existing records with inspectable
evidence, explicit uncertainty, and understood manual work after statement updates.
Use the lightweight [personal workflow review](docs/how-to/review-personal-workflows.md).
Private notes are optional; no telemetry or collection service is required.

- [ ] Choose the next unresolved question from actual future use. Check existing
  answers and evidence before proposing functionality; a development request
  alone does not establish personal question demand.
- [ ] Review question → existing answer/evidence → manual work → unresolved
  uncertainty → repeat after a statement update. Keep missing inputs distinct
  from calculation defects and documented limits.
- [ ] Reproduce an observed failure with synthetic inputs before a code fix.
  Select bounded changes to records, validation, calculations, or read contracts;
  no particular unresolved bug is established by the retrospective below.
  Route presentation, strategy, provider, and hosted-service needs to extensions.

### Initial retrospective, not outcome evidence

A sanitized local aggregate read on 2026-11-09 used fixed lexical categories over
historical project user prompts: 247 indexed sessions, 244 eligible before the
2026-11-09 16:00 UTC cutoff, and 875 deduplicated messages considered. It selected
3 owner-question sessions in 2026-10-26..2026-11-09, with overlapping categories:
income (2), holdings (1), and allocation (1). These are starting points for
inspecting existing workflows,
not independent-user observations or evidence of repeated successful use.

This initial triage has no observed outcomes, timings, baselines, or repeat-adoption
evidence. Zero lexical friction matches does not show absence of friction.
Broader development-category counts are not user demand; the retrospective proves
neither correctness, an unresolved bug, reduced effort, nor usefulness.

## Optional independent-use research

Use the existing [local measurement protocol](docs/how-to/measure-core-workflow.md)
if expanding beyond personal use. Independent onboarding, matched-workflow
baselines, and repeat-adoption research remain optional future work. They do not
block the personal review above. The protocol's blank template and synthetic
checks are not observations; independent completion, the proposed under-15-minute
target, comparative effort, and repeat adoption remain unvalidated.

- [ ] With voluntary independent participants, measure first-real-statement →
  review → portfolio answer/report without personal onboarding; record installation
  separately and retain failures and assistance.
- [ ] Compare matched supported tasks against existing workflows before claiming
  reduced effort or better discrepancy resolution; repeat after a statement update
  before claiming repeat adoption.
- [ ] Include sample size, observation window, and limitations beside each verdict.

## Delivery criteria

For each slice, identify supported inputs, core/extension ownership, compatibility
implications, and behavioral acceptance criteria. Verify relevant workflows with
focused local checks and remote CI for the full suite.

Calculation replay stays bounded to normalized inputs, selected parameters,
methods, recorded environment requirements, and results. Importer re-execution,
automatic environment installation, and report byte identity are outside that
contract. Keep incomplete evidence explicit and protect valid state on failure.

Remove delivered work from this file and document its supported behavior and
limitations in reference documentation. Extension opportunities are not a
conditional core backlog.
