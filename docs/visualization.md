# Visualization Module

## Scope

A minimal static HTML dashboard generated from local data.

## Input

- Portfolio profile and base currency from local `data/portfolio.json` (auto-seeded from `data-sample/portfolio.json` when missing and defaults are used)
- Time series from local `data/snapshots.jsonl` (auto-seeded from `data-sample/snapshots.jsonl` when missing and defaults are used)

## Output

- `out/dashboard.html`
  - Total portfolio value
  - Line chart of progress over time
  - Current allocation by asset class

## Design Constraints

- Zero frontend framework dependencies.
- Works offline.
- Easy to inspect and modify.

## Generate

```bash
rikdom visualize --out out/dashboard.html --include-current
```
