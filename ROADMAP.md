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
| Now, P1 | Explain changes between saved results | Compare captured evidence and methods; do not confuse revised facts with investment returns. |
| Ongoing, P1 | Validate usefulness and close demonstrated core gaps | Fix observed integrity, compatibility, or evidence problems without adopting downstream product responsibilities. |

Reliable external-agent reads are documented in the [read contract](docs/reference/agent-read-contract.md),
[context workflow](docs/how-to/use-portfolio-context.md), and [offline reader example](docs/how-to/read-portfolio-context-example.md).
They do not depend on run comparisons, a new protocol, report rendering, or
reconstruction of an importer environment.

## Explain differences between saved runs

**Outcome:** users and agents can explain why recorded results changed using
local evidence, without treating every difference as economic performance.

- [ ] Compare captured runs with pointers to source/review revisions, added
  activities, valuations/FX, parameters, methods, versions, and coverage.
- [ ] Isolate controlled source-correction, FX-vintage, and method changes;
  classify unexplained residuals as unresolved.
- [ ] Preserve scope/date/currency/method differences. Incompatible totals must
  not be presented as like-for-like returns.
- [ ] Expose comparison results through documented CLI/Python contracts with
  explicit errors, evidence references, and compatibility expectations.

## Validate the core workflow

Use the [local measurement protocol](docs/how-to/measure-core-workflow.md). Its
blank template and synthetic checks are not measured user observations; the
completion-time and repeat-use criteria below remain unvalidated.

- [ ] Measure independent users completing first-real-statement → review →
  portfolio answer/report without personal onboarding. Test a proposed
  under-15-minute target with installation recorded separately.
- [ ] Record attempted/completed workflows, elapsed time, unresolved discrepancies,
  and repeat use after a statement update. Include sample size and observation
  window beside each verdict; use voluntary feedback or local measurements.
- [ ] Compare the same supported task against an existing workflow before claiming
  reduced effort or better discrepancy resolution. Record setup, scope, failures,
  and successes.
- [ ] Use observed failures to select bounded fixes to records, validation,
  calculations, or read contracts. Route presentation, strategy, provider, and
  hosted-service needs to independently maintained extensions.

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
