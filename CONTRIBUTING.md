# Contributing to rikdom

Thanks for contributing to `rikdom`.

This guide explains how to propose changes, set up a local environment, and submit high-quality pull requests.

## Ways to contribute

- Fix bugs.
- Propose or implement features.
- Improve docs and examples.
- Add or improve plugins in `plugins/`.
- Improve tests and developer tooling.

## Before you start

- Check existing issues and pull requests to avoid duplicate work.
- For large changes, open an issue first to align on scope and design.
- Keep changes focused. Smaller PRs are reviewed and merged faster.

## Choose the right scope

Read [product scope and extension ownership](docs/explanation/product-scope.md)
before proposing a feature. Core changes should improve durable records,
validation, shared deterministic calculations, or reliable local evidence access.
Keep independently changing provider, regional, strategy, presentation, AI, and
service behavior in plugins, extension libraries, or separate repositories.

Prefer existing files and Python/CLI contracts over a new hook or service.
A plugin taxonomy label is not a commitment to implement a runtime stage.
Preserve supported APIs and calculations when introducing an extension.

## Development setup

Prerequisites:

- Python 3.10+
- `uv`: <https://docs.astral.sh/uv/getting-started/installation/>

Dependency freshness guard:

- This repository enforces `exclude-newer = "7 days"` via `uv.toml`.
- `uv add`, `uv lock`, and `uv sync` will reject package versions published in the last 7 days.

Install dependencies:

```bash
uv sync --extra schema --extra dev
```

Run a quick sanity check:

```bash
uv run rikdom validate --portfolio tests/fixtures/portfolio.json
```

Run a focused test module relevant to your change, for example:

```bash
uv run python -m unittest tests.test_cli_reconcile -v
```

Run lint checks:

```bash
make lint
```

## Development workflow

1. Create a branch from `main`.
2. Make focused commits with clear messages.
3. Add or update tests for behavioral changes.
4. Run focused validation and tests locally.
5. Open a pull request with context and rationale, then monitor its CI run for full-suite results.

Recommended branch naming:

- `fix/<short-description>`
- `feat/<short-description>`
- `docs/<short-description>`
- `refactor/<short-description>`

## Pull request guidelines

A good PR includes:

- Problem statement and why the change is needed.
- Summary of the approach and key tradeoffs.
- Linked issue(s), if applicable.
- Test evidence (commands run and results).
- Notes on backward compatibility and migration impact, if any.

PR checklist:

- [ ] Change is scoped and self-contained.
- [ ] Tests added/updated for new behavior.
- [ ] `make lint` passes.
- [ ] `uv run rikdom validate --portfolio tests/fixtures/portfolio.json` passes.
- [ ] Focused tests pass locally and the pull request's full CI run passes.
- [ ] Docs updated when behavior, schema, or CLI changes.
- [ ] Added/updated fixtures are sanitized (no real PII or real statement exports).

## Coding standards

- Follow existing project style and module patterns.
- Prefer small, composable functions and explicit types/structures.
- Avoid unrelated refactors in the same PR.
- Keep public behavior deterministic and local-first.
- Add comments only where intent is not obvious from code.

## Testing expectations

- Run only relevant test modules locally; the [CI workflow](.github/workflows/ci.yml) runs the full unit and plugin-contract suites on pull requests and pushes to `main`.
- Monitor the remote CI run before treating the full suite as verified. `make test` and `make check` include the full local suite and are not the routine local verification path.
- Every bug fix should include a regression test when possible.
- New features should include unit tests for happy path and edge cases.
- Prefer deterministic tests without network access.
- Keep test fixtures minimal and representative.
- Never commit fixtures containing PII; use synthetic names, randomized account IDs, and randomized numeric values.

## Schema and storage changes

Changes under `schema/`, storage behavior, or activity/projection semantics must:

- Preserve backward compatibility when feasible.
- Document incompatibilities and migration steps when not.
- Update relevant docs:
  - `docs/explanation/schema-design.md`
  - `docs/reference/storage-layout.md`
- Include validation/tests that cover the new constraints.

## Plugin contributions

For plugin-related work:

- Follow plugin contracts and manifest conventions in `docs/reference/plugin-manifest.md` and `docs/reference/plugin-hooks.md`.
- Keep plugin behavior explicit, idempotent, and auditable.
- Add tests covering manifest validation and runtime behavior.
- Document configuration and expected inputs/outputs.
- For REST or MCP data providers, use the `external/connector` contract in API
  `1.1`. Keep transport, provider rules, and authentication handling inside the plugin;
  see [connector hooks](docs/reference/plugin-hooks.md#connector-hooks) and the
  [brapi example connector](plugins/brapi/README.md). Include offline
  fixtures and mock external I/O in transport tests.

## Reporting bugs and requesting features

- Use GitHub issue templates:
  - `.github/ISSUE_TEMPLATE/bug_report.md`
  - `.github/ISSUE_TEMPLATE/feature_request.md`
- Include reproduction steps, expected behavior, and actual behavior.
- For parser/import issues, include a minimal sample input when possible.

## Security

The [Gitleaks workflow](.github/workflows/gitleaks.yml) scans the checked-out Git
history on pull requests and pushes to `main`, including secrets removed in later
commits. It uses the free CLI, requires no license secret, and redacts scanner
output. Gitleaks detects secret patterns; it does not guarantee that files contain
no personal data. Review fixtures and exports separately for privacy.

Before committing, install [Gitleaks 8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1)
and run this from the repository to check your staged changes:

```bash
(
  set -euo pipefail
  cd "$(git rev-parse --show-toplevel)"
  if [[ -e .gitleaksignore || -L .gitleaksignore ]]; then
    echo "Unexpected root .gitleaksignore; use reviewed rule-specific policy instead." >&2
    exit 1
  fi
  # Preserve repository-relative paths even with local diff.noprefix settings.
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.noprefix GIT_CONFIG_VALUE_0=false \
    gitleaks git . --staged --config .github/gitleaks.toml \
    --redact=100 --no-banner --no-color --ignore-gitleaks-allow
)
```

Both commands explicitly select [.github/gitleaks.toml](.github/gitleaks.toml),
which extends all built-in rules and allows only verified synthetic idempotency
assignments at exact fixture paths. Alternate root configurations are not selected;
root `.gitleaksignore` files are rejected, and inline `gitleaks:allow` comments do
not suppress findings.

Treat the selected policy and workflow as security-sensitive review targets:
changes to either can weaken detection and require independent review. The check
uses the checked-out versions of these files; it cannot protect against its own
policy or workflow being modified. No branch-protection settings were changed;
required checks and review enforcement depend on repository settings. CI runs
after upload, and the local staged check is voluntary.

If a credential is exposed, revoke or rotate it and remove it from the affected
commits before pushing. Do not add a baseline or broad allowlist to silence a
finding; investigate it privately and justify any narrowly scoped exception.

Do not publish sensitive vulnerabilities in a public issue.

Report security concerns privately through GitHub security reporting if available for this repository. If it is not available, open a minimal issue requesting a private contact channel.

## Communication and review etiquette

- Be respectful, specific, and technical in feedback.
- Assume good intent; discuss tradeoffs with evidence.
- Resolve review comments with code or clear reasoning.

## License

By contributing, you agree that your contributions are licensed under the MIT License used by this project.
