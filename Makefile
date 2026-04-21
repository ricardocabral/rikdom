.PHONY: help sync bootstrap validate validate-fixture aggregate snapshot visualize \
	plugins-list import-sample render-report storage-sync migrate-dry-run \
	test lint check

help:
	@echo "Common tasks:"
	@echo "  make sync             - Install/sync dependencies with uv"
	@echo "  make bootstrap        - Seed local data files from data-sample/"
	@echo "  make validate         - Validate default portfolio data"
	@echo "  make validate-fixture - Validate test fixture portfolio"
	@echo "  make aggregate        - Aggregate holdings by asset class"
	@echo "  make snapshot         - Append a historical snapshot"
	@echo "  make visualize        - Generate dashboard at out/dashboard.html"
	@echo "  make plugins-list     - List plugins in plugins/"
	@echo "  make import-sample    - Import sample statement using csv-generic"
	@echo "  make render-report    - Render report via quarto plugin"
	@echo "  make storage-sync     - Run duckdb storage sync plugin"
	@echo "  make migrate-dry-run  - Run schema migration in dry-run mode"
	@echo "  make lint             - Run ruff lint checks"
	@echo "  make test             - Run unit tests"
	@echo "  make check            - Run lint + validate-fixture + test"

sync:
	uv sync --extra schema

bootstrap:
	mkdir -p data
	cp -n data-sample/portfolio.json data/portfolio.json
	cp -n data-sample/snapshots.jsonl data/snapshots.jsonl

validate:
	uv run rikdom validate

validate-fixture:
	uv run rikdom validate --portfolio tests/fixtures/portfolio.json

aggregate:
	uv run rikdom aggregate

snapshot:
	uv run rikdom snapshot

visualize:
	uv run rikdom visualize --out out/dashboard.html --include-current

plugins-list:
	uv run rikdom plugins list --plugins-dir plugins

import-sample:
	uv run rikdom import-statement --plugin csv-generic --input data-sample/sample_statement.csv --write

render-report:
	uv run rikdom render-report --plugin quarto-portfolio-report --plugins-dir plugins

storage-sync:
	uv run rikdom storage-sync --plugin duckdb-storage --plugins-dir plugins

migrate-dry-run:
	uv run rikdom migrate --portfolio data-sample/portfolio.json --dry-run

test:
	uv run python -m unittest discover -s tests -v

lint:
	ruff check .

check: lint validate-fixture test
