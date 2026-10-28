.PHONY: help sync bootstrap validate validate-fixture aggregate reconcile snapshot viz \
	visualize render-report performance funded-ratio \
	plugins-list import-sample storage-sync migrate-dry-run \
	migrate-dry-run-policy validate-with-policy \
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
	@echo "  make performance      - Compute portfolio TWR and MWR"
	@echo "  make funded-ratio     - Compute policy objective funded ratios"
	@echo "  make viz              - Generate quickview + deep-dive via quarto plugin"
	@echo "  make plugins-list     - List plugins in plugins/"
	@echo "  make import-sample    - Import sample statement using csv-generic"
	@echo "  make storage-sync     - Run duckdb storage sync plugin"
	@echo "  make migrate-dry-run  - Run portfolio schema migration in dry-run mode"
	@echo "  make migrate-dry-run-policy - Run policy schema migration in dry-run mode"
	@echo "  make validate-with-policy   - Validate sample portfolio with cross-file policy account_id check"
	@echo "  make lint             - Run ruff lint checks"
	@echo "  make test             - Run unit tests"
	@echo "  make check            - Run lint + validate-fixture + test"

sync:
	uv sync --extra schema --extra dev

bootstrap:
	mkdir -p $(DATA_DIR) $(DATA_DIR)/benchmarks
	test -e $(DATA_DIR)/portfolio.json || cp -n data-sample/portfolio.json $(DATA_DIR)/portfolio.json
	test -e $(DATA_DIR)/snapshots.jsonl || cp -n data-sample/snapshots.jsonl $(DATA_DIR)/snapshots.jsonl
	test -e $(DATA_DIR)/policy.json || cp -n data-sample/policy.json $(DATA_DIR)/policy.json
	test -e $(DATA_DIR)/fx_rates.jsonl || cp -n data-sample/fx_rates.jsonl $(DATA_DIR)/fx_rates.jsonl
	for f in data-sample/benchmarks/*.jsonl; do \
		[ -e "$$f" ] || continue; \
		test -e $(DATA_DIR)/benchmarks/$$(basename "$$f") || cp -n "$$f" $(DATA_DIR)/benchmarks/$$(basename "$$f"); \
	done

validate:
	uv run rikdom validate $(WORKSPACE_ARGS)

validate-fixture:
	uv run rikdom validate --portfolio tests/fixtures/portfolio.json

aggregate:
	uv run rikdom aggregate $(WORKSPACE_ARGS)

reconcile:
	uv run rikdom reconcile $(WORKSPACE_ARGS)

snapshot:
	uv run rikdom snapshot $(WORKSPACE_ARGS)

performance:
	uv run rikdom performance $(WORKSPACE_ARGS) \
		$$(test -f $(DATA_DIR)/policy.json && echo "--policy $(DATA_DIR)/policy.json --benchmarks-dir $(DATA_DIR)/benchmarks")

funded-ratio:
	uv run rikdom funded-ratio $(WORKSPACE_ARGS) \
		--policy $(DATA_DIR)/policy.json

viz:
	uv run rikdom viz $(WORKSPACE_ARGS) --include-current

# Deprecated aliases for `viz` (kept one transition release).
visualize:
	@echo "[deprecation] 'make visualize' is deprecated; use 'make viz' instead." 1>&2
	@$(MAKE) viz

render-report:
	@echo "[deprecation] 'make render-report' is deprecated; use 'make viz' instead." 1>&2
	uv run rikdom viz $(WORKSPACE_ARGS)

plugins-list:
	uv run rikdom plugins list --plugins-dir plugins

import-sample:
	uv run rikdom import-statement $(WORKSPACE_ARGS) --plugin csv-generic --input data-sample/sample_statement.csv --write

storage-sync:
	uv run rikdom storage-sync $(WORKSPACE_ARGS) --plugin duckdb-storage --plugins-dir plugins

migrate-dry-run:
	uv run rikdom migrate --portfolio data-sample/portfolio.json --dry-run

migrate-dry-run-policy:
	uv run rikdom migrate-policy --policy data-sample/policy.json --dry-run

validate-with-policy:
	uv run rikdom validate --portfolio data-sample/portfolio.json --policy data-sample/policy.json

classify-fiis:
	uv run python scripts/apply_fii_classification.py \
		--portfolio $(DATA_DIR)/portfolio.json \
		--mapping $(DATA_DIR)/fii_classification.json

test:
	uv run python -m unittest discover -s tests -t . -v

lint:
	uv run ruff check .

check: lint validate-fixture test
