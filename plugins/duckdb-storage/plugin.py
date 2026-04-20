from __future__ import annotations

import sync as sync_impl
from rikdom.plugin_engine.hookspecs import hookimpl


class Plugin:
    @hookimpl
    def state_storage_sync(self, ctx, portfolio_path, snapshots_path, options):
        return sync_impl.sync_to_duckdb(portfolio_path, snapshots_path, options or {})

    @hookimpl
    def state_storage_health(self, ctx, options):
        db_path = (options or {}).get("db_path", "out/rikdom.duckdb")
        return {"status": "ok", "db_path": db_path}

