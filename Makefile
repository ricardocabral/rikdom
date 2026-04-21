.PHONY: help sync bootstrap validate validate-fixture aggregate snapshot visualize \
	plugins-list import-sample render-report storage-sync migrate-dry-run \
	test lint check

DATA_DIR ?= data
OUT_DIR ?= out
PORTFOLIO_NAME ?=

WORKSPACE_ARGS = --data-dir $(DATA_DIR) --out-root $(OUT_DIR)
ifneq ($(strip $(PORTFOLIO_NAME)),)
WORKSPACE_ARGS += --portfolio-name $(PORTFOLIO_NAME)
endif

help:
	@echo "Common tasks:"
	@echo "  variables: DATA_DIR=data OUT_DIR=out PORTFOLIO_NAME=<name>"
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
	mkdir -p $(DATA_DIR)
	cp -n data-sample/portfolio.json $(DATA_DIR)/portfolio.json
	cp -n data-sample/snapshots.jsonl $(DATA_DIR)/snapshots.jsonl

validate:
	uv run rikdom validate $(WORKSPACE_ARGS)

validate-fixture:
	uv run rikdom validate --portfolio tests/fixtures/portfolio.json

aggregate:
	uv run rikdom aggregate $(WORKSPACE_ARGS)

snapshot:
	uv run rikdom snapshot $(WORKSPACE_ARGS)

visualize:
	uv run rikdom visualize $(WORKSPACE_ARGS) --include-current

plugins-list:
	uv run rikdom plugins list --plugins-dir plugins

import-sample:
	uv run rikdom import-statement $(WORKSPACE_ARGS) --plugin csv-generic --input data-sample/sample_statement.csv --write

render-report:
	uv run rikdom render-report $(WORKSPACE_ARGS) --plugin quarto-portfolio-report --plugins-dir plugins

storage-sync:
	uv run rikdom storage-sync $(WORKSPACE_ARGS) --plugin duckdb-storage --plugins-dir plugins

migrate-dry-run:
	uv run rikdom migrate --portfolio data-sample/portfolio.json --dry-run

test:
	uv run python -m unittest discover -s tests -v

lint:
	ruff check .

check: lint validate-fixture test
