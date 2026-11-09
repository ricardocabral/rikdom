# Product scope and extension ownership

Rikdom maintains a local portfolio reference that outlasts any broker application,
report interface, or LLM. Its core owns durable facts, declared user intent,
validation, and reproducible financial meaning. Extensions and external agents
use that reference to acquire data, present it, or reason about decisions.

## What the core owns

- Readable, versioned JSON/JSONL records, stable identities, migrations, and
  preservation of extension data.
- Normalized import validation, provenance, reviewed corrections, reconciliation,
  and recoverable persistence.
- Explicit user policy and classifications as data, separate from investment
  recommendations and proposed actions.
- Deterministic calculations over declared inputs, with methods, dates,
  currencies, coverage, and limitations visible to every consumer.
- Documented local file, CLI, and Python contracts for users, scripts, reports,
  and external agents, plus integrity-checked exports and calculation replay.

A simple core can contain careful financial calculations. Shared arithmetic and
coverage checks prevent each LLM or interface from inventing a different meaning
for the same records. Supported return, income, valuation, and reviewed profit
calculations remain supported; this scope does not remove implemented behavior.
New specialized methods need a demonstrated shared need before entering core.

## What source of truth means

Canonical records express the accepted local state and its evidence. They do not
prove that a statement is complete, a provider observation is correct, or an
investment assumption will hold. Source observations, user reviews, declared
intent, and derived results remain distinguishable.

For example, an issuer's dividend announcement is external evidence. A payment
in an imported statement is evidence of a receipt. An LLM's prediction of next
month's income is a proposal or scenario. Neither an announcement nor a prediction
can silently become received cash.

An agent should be able to identify the portfolio revision or captured inputs,
relevant dates and scope, schema/method versions, source pointers, and data gaps
behind its answer. Calculations establish results only for their supported inputs.
Missing data must remain unknown, and changed inputs must not be mistaken for
investment performance.

The user chooses the reasoning tool. Rikdom supplies local records and
calculation results without invoking an LLM. Agent proposals become canonical
only through explicit user acceptance and the applicable validated write workflow.
The [roadmap](../../ROADMAP.md) prioritizes recurring questions and observed core gaps; this principle
does not imply a new context endpoint or agent protocol already exists.

## Where additional value belongs

These are ownership examples for independent work, not delivery commitments or
prerequisites for the core roadmap.

| Opportunity | Appropriate owner | Boundary with Rikdom |
| --- | --- | --- |
| Broker connections, regional catalogs, market-data acquisition | Provider plugins or extension libraries | Normalize explicit inputs with identity, dates, provenance, coverage, and licensing; keep provider dependencies outside core. |
| Dashboards, mobile/desktop interfaces, report designs | Output plugins or separate applications | Consume the same records/results; keep layout, application services, and UI dependencies outside core. |
| Rebalance recommendations, optimizers, simulations, specialized lot methods | Independently versioned calculation/strategy libraries | Read policy and supported evidence; label assumptions and proposed/simulated state; preserve real records. |
| Jurisdiction-specific tax workpapers, filing, or payments | Separate regional libraries or applications | Version legal rules and years independently; consume portfolio evidence without embedding jurisdiction rules in core. |
| AI explanations, model execution, decision agents, MCP servers | External agent integrations or separate repositories | Select the model/protocol outside core, cite local evidence, and submit proposed changes for review. |
| Scheduled refresh, notifications, background synchronization | External orchestration or OS scheduling | Invoke explicit commands with scoped credentials; preserve idempotency and expose failures. |
| Encryption, backups, secret storage, credential revocation | OS facilities, dedicated tools, or provider adapters | Protect local files and provider credentials; core exports stay portable and integrity-checked. |
| Execution of untrusted plugins | Separate constrained runner or host environment | Own enforced filesystem/network/secret isolation; the in-process plugin runtime remains trusted code. |
| Collective dividend-receipt comparisons or other shared-data services | Separate service/repository | Keep participation optional and peer evidence external; peer observations cannot establish a user's entitlement or receipt. |
| Re-running historical importers and reconstructing their environments | Importer tooling or an external environment manager | Retain original statements and trusted dependencies separately from normalized calculation replay. |

An extension can use files or Python APIs without a new engine hook. A separate
repository may own its own roadmap, dependencies, service operation, and release
cycle. Packaging an idea as a plugin does not make its business logic a core duty.

## Local operation and trust

Core records, calculations, and file-based workflows remain usable offline after
installation. Provider queries are explicit, optional operations. Local-first
also means that a remote response is not automatically promoted to canonical
portfolio evidence.

Installed plugins execute as trusted Python with the user's process privileges.
Descriptions and read-only declarations are interface contracts, not enforcement.
Use only trusted plugins in this runtime. A runner claiming support for untrusted
code must enforce and verify isolation independently; core does not promise a
general sandbox or a permission/security platform.

Core protects its own write boundaries, integrity checks, and diagnostics.
Provider adapters own authentication and minimum necessary requests; external
tools own encrypted backup and OS-level protection. Calculation replay records
requirements and verifies results without downloading data, installing an
environment, executing bundled code, or preserving a whole application runtime.

## Keeping the boundary stable

A core addition must improve durable records, validation, shared financial
meaning, or reliable access to that evidence. It needs a concrete consumer,
supported inputs, compatibility rules, and behavioral checks. Prefer an existing
file/API contract when it already serves the need.

An application feature, new provider, or taxonomy label alone does not justify a
new core abstraction. Preserve supported contracts while placing independently
changing provider, regional, strategy, presentation, and service behavior in its
own library or project.

See [schema design](schema-design.md), [plugin architecture](plugin-architecture.md),
and [calculation trust](calculation-trust.md) for the corresponding contracts and
trust boundaries.
