# Visualization Module

## Scope

Visualization is plugin-driven through `quarto-portfolio-report`.

It generates two linked HTML artifacts:

- `dashboard.html` (quickview)
- `portfolio-report.html` (deep-dive)

## Input

- Portfolio profile and base currency from local `data/portfolio.json`
- Time series from local `data/snapshots.jsonl`
- Optional current-state synthetic snapshot via `--include-current`

## Output

Using `rikdom viz`:

- `out/dashboard.html` (quickview)
- `out/portfolio-report.html` (deep dive)

Both pages link to each other.

## Generate

```bash
rikdom viz --out out/dashboard.html --include-current
```
