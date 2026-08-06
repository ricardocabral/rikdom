# Migração do histórico de IRPF — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arquivar itens do XML IRPF de 2025 sem substituir posições correntes e deixar a carteira ativa validável.

**Architecture:** Um script local carrega o XML pelo importador existente, grava um arquivo histórico determinístico e remove somente holdings `irpf-*` cujo valor é zero. A operação é prévia por padrão, com backup e escrita explícita.

**Tech Stack:** Python 3.10+, `defusedxml` via importador IRPF, JSON, `unittest`.

## Global Constraints

- Nunca copiar nem versionar a declaração XML real.
- Nunca alterar valor, quantidade, data ou proveniência de holding ativa.
- Toda escrita exige `--write`; a prévia não altera arquivos.

---

### Task 1: Implementar a transformação pura

**Files:**
- Create: `scripts/migrate_irpf_history.py`
- Test: `tests/test_migrate_irpf_history.py`

**Interfaces:**
- Produces: `build_history_document(xml_path: Path) -> dict` e `split_active_holdings(portfolio: dict) -> tuple[dict, list[dict]]`.

- [ ] **Step 1: Write the failing test**

```python
def test_split_active_holdings_archives_only_zero_value_irpf_rows():
    active, archived = split_active_holdings({"holdings": [
        {"id": "irpf-0301-tk-demo3", "market_value": {"amount": 0, "currency": "BRL"}},
        {"id": "irpf-0701-cnpj-active", "market_value": {"amount": 10, "currency": "BRL"}},
        {"id": "b3:current", "market_value": {"amount": 20, "currency": "BRL"}},
    ]})
    assert [h["id"] for h in active["holdings"]] == ["irpf-0701-cnpj-active", "b3:current"]
    assert [h["id"] for h in archived] == ["irpf-0301-tk-demo3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_migrate_irpf_history.MigrateIrpfHistoryTests.test_split_active_holdings_archives_only_zero_value_irpf_rows`

- [ ] **Step 3: Write minimal implementation**

Implement a deep-copying splitter that recognizes `irpf-` ids and exactly zero numeric BRL values.

- [ ] **Step 4: Run test to verify it passes**

Run the Task 1 test command.

### Task 2: Implementar prévia e escrita protegida

**Files:**
- Modify: `scripts/migrate_irpf_history.py`
- Modify: `tests/test_migrate_irpf_history.py`

**Interfaces:**
- Produces: CLI `--portfolio`, `--input`, `--archive`, `--write`.

- [ ] **Step 1: Write the failing test**

```python
def test_run_dry_run_leaves_portfolio_unchanged_and_reports_archive(tmp_path):
    result = run_migration(portfolio_path, xml_path, archive_path, write=False)
    assert json.loads(portfolio_path.read_text()) == original
    assert not archive_path.exists()
    assert result["archived_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_migrate_irpf_history.MigrateIrpfHistoryTests.test_run_dry_run_leaves_portfolio_unchanged_and_reports_archive`

- [ ] **Step 3: Write minimal implementation**

Load the XML through the plugin, include SHA-256 and all normalized items in the archive, and write the archive plus an atomic portfolio backup only when `--write` is supplied.

- [ ] **Step 4: Run test to verify it passes**

Run the Task 2 test command.

### Task 3: Verificar e aplicar a migração real

**Files:**
- Modify locally: `data/portfolio.json`
- Create locally: `data/irpf-history/2025.json`

- [ ] **Step 1: Run the test module and the full suite**

Run: `uv run python -m unittest tests.test_migrate_irpf_history` and `uv run python -m unittest discover -s tests -p 'test_*.py'`.

- [ ] **Step 2: Execute a dry run against the real XML**

Run the script without `--write`; verify no active nonzero position is listed for removal.

- [ ] **Step 3: Execute with `--write` and validate**

Run with explicit paths to the workspace `data/portfolio.json`, `data/irpf-history/2025.json`, and the supplied XML; then run `make validate`.
