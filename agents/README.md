# Agent Skills And Prompts

This project includes ready-to-use instruction files so AI agents can reason over the schema and local data consistently.

## Included

- `agents/codex/SKILL.md` for OpenAI Codex-style coding agents
- `agents/openai-codex/SKILL.md` variant for OpenAI workflows
- `agents/claude/CLAUDE.md` for Claude Code / Claude projects

## Shared Agent Principles

- Treat JSON as source of truth (`data/portfolio.json`, `data/snapshots.jsonl`).
- Preserve unknown fields under `extensions`/`metadata`.
- Never remove holdings without explicit user intent.
- Prefer additive schema evolution and version bumps.
- Output decisions with file and line references when suggesting edits.
