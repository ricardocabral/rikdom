from __future__ import annotations

import pluggy


hookspec = pluggy.HookspecMarker("rikdom")
hookimpl = pluggy.HookimplMarker("rikdom")


class RikdomHookSpecs:
    @hookspec(firstresult=True)
    def source_input(self, ctx, input_path):
        """Return normalized statement payload."""

    @hookspec
    def asset_type_catalog(self, ctx):
        """Return a list of asset type definitions."""

    @hookspec(firstresult=True)
    def output(self, ctx, request):
        """Render output artifacts and return result payload."""

    @hookspec(firstresult=True)
    def state_storage_sync(self, ctx, portfolio_path, snapshots_path, options):
        """Sync canonical JSON data into storage backend."""

    @hookspec(firstresult=True)
    def state_storage_query(self, ctx, query_name, params):
        """Query a storage backend by named query."""

    @hookspec(firstresult=True)
    def state_storage_health(self, ctx, options):
        """Return storage backend health metadata."""

    @hookspec
    def observability(self, ctx, event, payload):
        """Emit logs/metrics/traces."""

    @hookspec
    def audit_trail(self, ctx, event, payload):
        """Record auditable events."""

