# quarto-portfolio-report

Pluggy `output` plugin that renders a portfolio report with Quarto.

## Prerequisites

Install Quarto CLI and ensure it is available in `PATH`:

```bash
brew install --cask quarto
quarto --version
```

If Quarto is missing, the plugin still runs but generates a fallback HTML artifact.

## Run

```bash
uv run rikdom render-report \
  --plugin quarto-portfolio-report \
  --plugins-dir plugins \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --out-dir out/reports
```
