from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

from rikdom.plugin_engine.errors import PluginEngineError
from rikdom.storage import load_json, load_jsonl


def _sha256_file(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return hashlib.sha256(b"").hexdigest()
    data = p.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _load_duckdb():
    try:
        return importlib.import_module("duckdb")
    except ModuleNotFoundError as exc:
        raise PluginEngineError(
            "duckdb Python package is required by plugin 'duckdb-storage'. "
            "Install it with: pip install duckdb"
        ) from exc


def _migration_paths() -> list[Path]:
    root = Path(__file__).resolve().parent / "migrations"
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*.sql") if p.is_file())


def _run_migrations(conn) -> None:
    for migration_path in _migration_paths():
        sql = migration_path.read_text(encoding="utf-8")
        statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
        for statement in statements:
            conn.execute(statement)


def _normalize_portfolio_header(portfolio: dict[str, Any]) -> tuple:
    profile = portfolio.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    settings = portfolio.get("settings")
    if not isinstance(settings, dict):
        settings = {}

    portfolio_id = str(profile.get("portfolio_id", "")).strip() or "default"
    return (
        portfolio_id,
        str(portfolio.get("schema_version", "")) or None,
        str(portfolio.get("schema_uri", "")) or None,
        str(profile.get("owner_kind", "")) or None,
        str(profile.get("display_name", "")) or None,
        str(profile.get("country", "")) or None,
        str(settings.get("base_currency", "")) or None,
        str(settings.get("timezone", "")) or None,
        str(profile.get("created_at", "")) or None,
        json.dumps(portfolio, ensure_ascii=False, sort_keys=True),
    )


def _normalize_holdings(
    portfolio: dict[str, Any],
) -> list[tuple]:
    profile = portfolio.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    portfolio_id = str(profile.get("portfolio_id", "")).strip() or "default"

    holdings = portfolio.get("holdings")
    if not isinstance(holdings, list):
        return []

    rows: list[tuple] = []
    for idx, holding in enumerate(holdings, start=1):
        if not isinstance(holding, dict):
            continue

        identifiers = holding.get("identifiers")
        if not isinstance(identifiers, dict):
            identifiers = {}
        market_value = holding.get("market_value")
        if not isinstance(market_value, dict):
            market_value = {}

        holding_id = str(holding.get("id", "")).strip() or f"holding-{idx}"
        rows.append(
            (
                holding_id,
                portfolio_id,
                str(holding.get("asset_type_id", "")) or None,
                str(holding.get("label", "")) or None,
                str(identifiers.get("ticker", "")) or None,
                str(identifiers.get("isin", "")) or None,
                _to_float(holding.get("quantity")),
                _to_float(market_value.get("amount")),
                str(market_value.get("currency", "")) or None,
                str(holding.get("as_of", "")) or None,
                json.dumps(holding, ensure_ascii=False, sort_keys=True),
            )
        )
    return rows


def _normalize_snapshots(snapshots: list[dict[str, Any]]) -> list[tuple]:
    rows: list[tuple] = []
    for idx, snapshot in enumerate(snapshots, start=1):
        if not isinstance(snapshot, dict):
            continue

        totals = snapshot.get("totals")
        if not isinstance(totals, dict):
            totals = {}
        timestamp = str(snapshot.get("timestamp", "")).strip() or f"snapshot-{idx}"

        rows.append(
            (
                timestamp,
                str(snapshot.get("base_currency", "")) or None,
                _to_float(totals.get("portfolio_value_base")),
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            )
        )
    return rows


def _set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO _rikdom_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """,
        [key, value],
    )


def sync_to_duckdb(portfolio_path: str, snapshots_path: str, options: dict) -> dict:
    options = options or {}
    db_path = Path(options.get("db_path", "out/rikdom.duckdb"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    duckdb = _load_duckdb()

    portfolio = load_json(portfolio_path)
    snapshots = load_jsonl(snapshots_path)
    source_hash_portfolio = _sha256_file(portfolio_path)
    source_hash_snapshots = _sha256_file(snapshots_path)

    header_row = _normalize_portfolio_header(portfolio)
    holdings_rows = _normalize_holdings(portfolio)
    snapshot_rows = _normalize_snapshots(snapshots)

    conn = duckdb.connect(str(db_path))
    try:
        _run_migrations(conn)

        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute("DELETE FROM portfolio_header")
            conn.execute("DELETE FROM holdings")
            conn.execute("DELETE FROM snapshots")

            conn.execute(
                """
                INSERT INTO portfolio_header (
                    portfolio_id,
                    schema_version,
                    schema_uri,
                    owner_kind,
                    display_name,
                    country,
                    base_currency,
                    timezone,
                    created_at,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                list(header_row),
            )

            if holdings_rows:
                conn.executemany(
                    """
                    INSERT INTO holdings (
                        holding_id,
                        portfolio_id,
                        asset_type_id,
                        label,
                        ticker,
                        isin,
                        quantity,
                        market_value_amount,
                        market_value_currency,
                        as_of,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    holdings_rows,
                )

            if snapshot_rows:
                conn.executemany(
                    """
                    INSERT INTO snapshots (
                        snapshot_ts,
                        base_currency,
                        portfolio_value_base,
                        payload_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    snapshot_rows,
                )

            _set_meta(conn, "source_hash_portfolio", source_hash_portfolio)
            _set_meta(conn, "source_hash_snapshots", source_hash_snapshots)

            conn.execute("COMMIT")
        except Exception:  # noqa: BLE001
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    return {
        "rows_written": {
            "portfolio_header": 1,
            "holdings": len(holdings_rows),
            "snapshots": len(snapshot_rows),
        },
        "db_path": str(db_path),
        "source_hash_portfolio": source_hash_portfolio,
        "source_hash_snapshots": source_hash_snapshots,
    }
