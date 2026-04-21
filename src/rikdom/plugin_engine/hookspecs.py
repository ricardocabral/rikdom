from __future__ import annotations

import pluggy


hookspec = pluggy.HookspecMarker("rikdom")
hookimpl = pluggy.HookimplMarker("rikdom")


class RikdomHookSpecs:
    @hookspec(firstresult=True)
    def source_input(self, ctx, input_path):
        """Return normalized statement payload.

        Stability: Stable (v1).
        Dispatch: firstresult — first non-None result wins.
        """

    @hookspec
    def asset_type_catalog(self, ctx):
        """Return a list of asset type definitions.

        Stability: Stable (v1).
        Dispatch: fan-out — all implementations are called.
        """

    @hookspec(firstresult=True)
    def output(self, ctx, request):
        """Render output artifacts and return result payload.

        Stability: Stable (v1).
        Dispatch: firstresult — first non-None result wins.
        """

    @hookspec(firstresult=True)
    def state_storage_sync(self, ctx, portfolio_path, snapshots_path, options):
        """Sync canonical JSON data into storage backend.

        Stability: Stable (v1).
        Dispatch: firstresult — first non-None result wins.
        """

    @hookspec(firstresult=True)
    def state_storage_query(self, ctx, query_name, params):
        """Query a storage backend by named query.

        Stability: Stable (v1).
        Dispatch: firstresult — first non-None result wins.
        """

    @hookspec(firstresult=True)
    def state_storage_health(self, ctx, options):
        """Return storage backend health metadata.

        Stability: Stable (v1).
        Dispatch: firstresult — first non-None result wins.
        """

    @hookspec
    def observability(self, ctx, event, payload):
        """Emit logs/metrics/traces.

        Stability: Stable (v1).
        Dispatch: fan-out — all implementations are called.
        """

    @hookspec
    def audit_trail(self, ctx, event, payload):
        """Record auditable events.

        Stability: Stable (v1).
        Dispatch: fan-out — all implementations are called.
        """


# Programmatic stability metadata for each hook (v1 freeze).
# Keys mirror the method names on RikdomHookSpecs; values are tier strings
# ("stable" in v1). Importable by plugins-list tooling and docs generators.
HOOK_STABILITY: dict[str, str] = {
    "source_input": "stable",
    "asset_type_catalog": "stable",
    "output": "stable",
    "state_storage_sync": "stable",
    "state_storage_query": "stable",
    "state_storage_health": "stable",
    "observability": "stable",
    "audit_trail": "stable",
}
