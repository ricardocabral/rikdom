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

Quick target from repo root:

```bash
make render-report
```

Full command:

```bash
uv run rikdom render-report \
  --plugin quarto-portfolio-report \
  --plugins-dir plugins \
  --portfolio data-sample/portfolio.json \
  --snapshots data-sample/snapshots.jsonl \
  --out-dir out/reports
```
