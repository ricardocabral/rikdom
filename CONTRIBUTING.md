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

## Development setup

Prerequisites:

- Python 3.10+
- `uv`: <https://docs.astral.sh/uv/getting-started/installation/>

Install dependencies:

```bash
uv sync --extra schema
```

Run a quick sanity check:

```bash
uv run rikdom validate --portfolio data/portfolio.json
```

Run the test suite:

```bash
uv run python -m unittest discover -s tests -v
```

## Development workflow

1. Create a branch from `main`.
2. Make focused commits with clear messages.
3. Add or update tests for behavioral changes.
4. Run validation and tests locally.
5. Open a pull request with context and rationale.

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
- [ ] `uv run rikdom validate --portfolio data/portfolio.json` passes.
- [ ] `uv run python -m unittest discover -s tests -v` passes.
- [ ] Docs updated when behavior, schema, or CLI changes.

## Coding standards

- Follow existing project style and module patterns.
- Prefer small, composable functions and explicit types/structures.
- Avoid unrelated refactors in the same PR.
- Keep public behavior deterministic and local-first.
- Add comments only where intent is not obvious from code.

## Testing expectations

- Every bug fix should include a regression test when possible.
- New features should include unit tests for happy path and edge cases.
- Prefer deterministic tests without network access.
- Keep test fixtures minimal and representative.

## Schema and storage changes

Changes under `schema/`, storage behavior, or activity/projection semantics must:

- Preserve backward compatibility when feasible.
- Document incompatibilities and migration steps when not.
- Update relevant docs:
  - `docs/schema-design.md`
  - `docs/storage.md`
- Include validation/tests that cover the new constraints.

## Plugin contributions

For plugin-related work:

- Follow plugin contracts and manifest conventions in `docs/plugin-system.md`.
- Keep plugin behavior explicit, idempotent, and auditable.
- Add tests covering manifest validation and runtime behavior.
- Document configuration and expected inputs/outputs.

## Reporting bugs and requesting features

- Use GitHub issue templates:
  - `.github/ISSUE_TEMPLATE/bug_report.md`
  - `.github/ISSUE_TEMPLATE/feature_request.md`
- Include reproduction steps, expected behavior, and actual behavior.
- For parser/import issues, include a minimal sample input when possible.

## Security

Do not publish sensitive vulnerabilities in a public issue.

Report security concerns privately through GitHub security reporting if available for this repository. If it is not available, open a minimal issue requesting a private contact channel.

## Communication and review etiquette

- Be respectful, specific, and technical in feedback.
- Assume good intent; discuss tradeoffs with evidence.
- Resolve review comments with code or clear reasoning.

## License

By contributing, you agree that your contributions are licensed under the MIT License used by this project.
