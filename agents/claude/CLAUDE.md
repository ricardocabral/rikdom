# Claude Instructions For Rikdom

You are working on a local-first wealth portfolio schema project.

## Primary Objectives

- Keep user financial data portable and readable as plain JSON.
- Avoid lock-in to any broker, SaaS, or visualization stack.
- Preserve backward compatibility across schema versions.

## Guardrails

- Do not introduce opaque binary formats.
- Do not require cloud services for core functionality.
- Preserve unknown fields in `metadata` and `extensions`.
- Keep plugin imports deterministic and auditable.

## Common Commands

```bash
rikdom validate --portfolio data/portfolio.json
rikdom aggregate --portfolio data/portfolio.json
rikdom snapshot --portfolio data/portfolio.json --snapshots data/snapshots.jsonl
rikdom visualize --portfolio data/portfolio.json --snapshots data/snapshots.jsonl --out out/dashboard.html --include-current
```
