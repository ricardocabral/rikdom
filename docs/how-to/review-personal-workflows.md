# Review recurring personal portfolio questions

Use an actual portfolio question to check what Rikdom already answers and choose
the next bounded improvement. This is the primary [roadmap](../../ROADMAP.md)
progress signal for personal use; AI-assisted owner use does not establish
independent onboarding or adoption.

Keep any notes in a private text file outside the repository. Notes and timings
are optional; this review needs no telemetry, uploads, new schema, or service.

1. **Choose a question from actual use.** State the period, currency, relevant
   scope, and what would count as an answer. Possible topics include received
   income, current holdings, or allocation; these are examples, not a backlog of
   proven gaps. Choose the next unresolved question when it arises rather than
   treating implementation requests or retrospective category counts as demand.

2. **Inspect the existing answer and evidence.** Start with the
   [income guide](summarize-income.md) or the
   [portfolio context workflow](use-portfolio-context.md), which also covers
   current holdings/allocation reads. Check dates, methods, currencies, warnings,
   exclusions, source coverage, and reviewed decisions against the question.
   Keep supporting references local. Record what is answered and what cannot be
   established; an output file or an empty result alone is not a verified answer.

3. **Identify manual work.** Note any source checks, corrections, conversions,
   retries, or human/AI assistance needed to reach the answer. Distinguish using
   an existing supported workflow from work that still requires a workaround.
   No stopwatch or comparison workflow is required. Claims of less effort need
   a matched baseline; remembered effort does not establish improvement.

4. **Name the unresolved uncertainty.** Separate missing source evidence,
   documented limits, unclear instructions, and suspected defects. If existing
   behavior answers the question, say so; do not invent a bug to fill the roadmap.
   For a suspected defect, create a small synthetic reproduction with expected
   behavior grounded in the supported contract before changing code. Keep its
   cause unproven until a check isolates it. Apply
   [product scope](../explanation/product-scope.md#keeping-the-boundary-stable)
   when deciding whether a bounded fix belongs in core or an extension.

5. **Repeat after a statement update.** Follow the existing
   [import and review workflow](import-a-statement.md), then ask the same question
   using the updated records and reviewed decisions. Check whether the answer
   and its evidence update, what manual work recurs, and what remains unknown.
   Reimporting an unchanged statement only checks idempotency. If no new statement
   is available, leave the repeat check pending; do not infer success or failure.

Use the sequence **question → existing answer/evidence → manual work → unresolved
uncertainty → statement-update repeat** for any optional private note. Select the
next change from the unresolved question, not the number of features delivered.
A retrospective can suggest workflows to inspect; it cannot prove outcomes or
replace this future-use check. Synthetic reproductions verify behavior, not
personal usefulness or independent adoption.

Keep portfolio details, figures, broker/instrument/account identities, statements,
source paths, raw logs, and transcript quotes out of git and GitHub. If describing
a fix publicly, use only synthetic inputs and a sanitized description. For
optional independent onboarding, timing, baseline, or repeat-adoption research,
use the [measurement protocol](measure-core-workflow.md) and retain its limits.
