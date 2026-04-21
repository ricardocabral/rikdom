# duckdb-storage

Pluggy `state/storage` plugin that mirrors canonical portfolio JSON into DuckDB.

## Prerequisites

Install the Python package in this project environment:

```bash
uv add duckdb
uv run python -c "import duckdb; print(duckdb.__version__)"
```

Alternative for temporary environments:

```bash
uv pip install duckdb
```

## Run

Quick target from repo root:

```bash
make storage-sync
```

Full command:

```bash
uv run rikdom storage-sync \
  --plugin duckdb-storage \
  --plugins-dir plugins \
  --portfolio data/portfolio.json \
  --snapshots data/snapshots.jsonl \
  --db-path out/rikdom.duckdb
```
