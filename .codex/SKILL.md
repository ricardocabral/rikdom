# Skill Router: Rikdom Codex Skills

Use this file to choose the right skill for the user intent.

## Which Skill To Use

- For novice users asking portfolio questions, analysis, summaries, allocation checks, trend checks, or basic imports: use `.codex/skills/rikdom-portfolio-analyst/SKILL.md`.
- For advanced users extending rikdom internals, schemas, plugin contracts, plugin code, or engine wiring: use `.codex/skills/rikdom-extensibility-engineer/SKILL.md`.

## Shared Rule

Both skills require asking for portfolio path context first:

`What is your rikdom portfolio data path? You can send: (1) the data directory, (2) a full path to portfolio.json, or (3) the workspace root + portfolio name.`
