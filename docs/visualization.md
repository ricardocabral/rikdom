# Visualization Module

## Scope

A minimal static HTML dashboard generated from local data.

## Input

- Portfolio profile and base currency from `data/portfolio.json`
- Time series from `data/snapshots.jsonl`

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
rikdom visualize --portfolio data/portfolio.json --snapshots data/snapshots.jsonl --out out/dashboard.html --include-current
```
