from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from .contracts import OutputRequest, PluginContext
from .errors import PluginEngineError
from .loader import discover_plugins
from .manifest import PluginManifest
from .runtime import build_manager, load_plugin_instance


# Hooks exposed by the v1 plugin API that are eligible for contract testing.
# Keys map to dispatch style: "firstresult" (single plugin result) or "fanout"
# (pluggy returns a list of per-plugin results that we unwrap for the sole
# registered plugin under test).
HOOK_DISPATCH: dict[str, str] = {
    "source_input": "firstresult",
    "output": "firstresult",
    "state_storage_sync": "firstresult",
    "state_storage_query": "firstresult",
    "state_storage_health": "firstresult",
    "asset_type_catalog": "fanout",
    "observability": "fanout",
    "audit_trail": "fanout",
}

# Default keys stripped before equality/determinism comparison. Plugins produce
# these as run-scoped timestamps and they are not part of the deterministic
# contract. Individual fixture cases may extend this list via `ignore_fields`.
DEFAULT_IGNORE_FIELDS: tuple[str, ...] = ("generated_at",)

SCHEMA_RESOURCE_MAP: dict[str, str] = {
    "plugin-statement": "plugin-statement.schema.json",
    "portfolio": "portfolio.schema.json",
    "snapshot": "snapshot.schema.json",
}

# Repo-root schema directory. These JSON Schemas still live outside the
# installed package (see `schema/`); resolve relative to this module so the
# contract runner works both from a source checkout and when invoked by the
# test harness's CWD-independent discovery.
_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schema"


@dataclass(slots=True)
class FixtureCase:
    plugin_name: str
    case_name: str
    fixture_dir: Path
    hook: str
    spec: dict[str, Any]
    expected_payload: Any | None
    expected_error: dict[str, Any] | None
    ignore_fields: tuple[str, ...]
    validate_schema: str | None
    requires: tuple[str, ...] = ()


@dataclass(slots=True)
class CaseResult:
    payload: Any | None = None
    error: BaseException | None = None
    raw_normalized: bytes | None = None


@dataclass(slots=True)
class PluginCoverage:
    plugin_name: str
    declared_hooks: set[str] = field(default_factory=set)
    covered_hooks: set[str] = field(default_factory=set)


@lru_cache(maxsize=None)
def _load_schema(name: str) -> Draft202012Validator:
    resource_name = SCHEMA_RESOURCE_MAP.get(name)
    if not resource_name:
        raise PluginEngineError(f"Unknown schema alias: {name!r}")
    schema_path = _SCHEMA_DIR / resource_name
    if not schema_path.exists():
        raise PluginEngineError(f"Schema not found: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _strip_ignored(value: Any, ignore: set[str]) -> Any:
    if isinstance(value, dict):
        return {k: _strip_ignored(v, ignore) for k, v in value.items() if k not in ignore}
    if isinstance(value, list):
        return [_strip_ignored(v, ignore) for v in value]
    return value


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _discover_input_file(fixture_dir: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = fixture_dir / explicit
        return p if p.exists() else None
    for candidate in sorted(fixture_dir.glob("input.*")):
        return candidate
    return None


def _case_from_dir(plugin_name: str, fixture_dir: Path) -> FixtureCase:
    case_json_path = fixture_dir / "case.json"
    if not case_json_path.exists():
        raise PluginEngineError(f"Missing case.json in fixture {fixture_dir}")
    spec = _load_json(case_json_path)
    hook = spec.get("hook")
    if hook not in HOOK_DISPATCH:
        raise PluginEngineError(
            f"Fixture {fixture_dir} declares unknown hook {hook!r}; "
            f"must be one of {sorted(HOOK_DISPATCH)}"
        )

    expected_error_path = fixture_dir / "expected_error.json"
    expected_error = _load_json(expected_error_path) if expected_error_path.exists() else None

    expected_payload: Any | None = None
    if expected_error is None:
        expected_json_path = fixture_dir / "expected.json"
        expected_jsonl_path = fixture_dir / "expected.jsonl"
        if expected_json_path.exists():
            expected_payload = _load_json(expected_json_path)
        elif expected_jsonl_path.exists():
            expected_payload = _load_jsonl(expected_jsonl_path)
        else:
            raise PluginEngineError(
                f"Fixture {fixture_dir} is missing expected.json, expected.jsonl, "
                "or expected_error.json"
            )

    ignore = set(DEFAULT_IGNORE_FIELDS) | set(spec.get("ignore_fields", []) or [])
    requires = tuple(spec.get("requires", []) or [])
    return FixtureCase(
        plugin_name=plugin_name,
        case_name=fixture_dir.name,
        fixture_dir=fixture_dir,
        hook=hook,
        spec=spec,
        expected_payload=expected_payload,
        expected_error=expected_error,
        ignore_fields=tuple(sorted(ignore)),
        validate_schema=spec.get("validate_schema"),
        requires=requires,
    )


def missing_requirements(case: FixtureCase) -> list[str]:
    """Return the subset of `case.requires` modules that are not importable."""
    import importlib.util as _ilu

    missing: list[str] = []
    for module_name in case.requires:
        if _ilu.find_spec(module_name) is None:
            missing.append(module_name)
    return missing


def discover_fixtures(plugins_dir: str | Path) -> list[FixtureCase]:
    root = Path(plugins_dir)
    cases: list[FixtureCase] = []
    for plugin_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        fixtures_root = plugin_dir / "fixtures"
        if not fixtures_root.is_dir():
            continue
        for fixture_dir in sorted(p for p in fixtures_root.iterdir() if p.is_dir()):
            cases.append(_case_from_dir(plugin_dir.name, fixture_dir))
    return cases


def _load_plugin(plugin_name: str, plugins_dir: Path):
    manifest: PluginManifest | None = None
    for m in discover_plugins(plugins_dir):
        if m.name == plugin_name:
            manifest = m
            break
    if manifest is None:
        raise PluginEngineError(f"Plugin {plugin_name!r} not found under {plugins_dir}")
    plugin_obj = load_plugin_instance(plugins_dir / plugin_name, manifest)
    pm = build_manager()
    pm.register(plugin_obj, name=manifest.name)
    return pm, manifest, plugin_obj


def declared_hooks(plugin_obj: Any) -> set[str]:
    """Return the set of v1 hook names the loaded plugin instance implements.

    Pluggy marks @hookimpl methods with a `_hookimpl_opts` attribute. This
    introspection avoids coupling fixture coverage to the manifest's
    plugin_types taxonomy, which is coarser than individual hook surface.
    """
    hooks: set[str] = set()
    for hook_name in HOOK_DISPATCH:
        method = getattr(plugin_obj, hook_name, None)
        if method is None:
            continue
        # Accept either pluggy-tagged methods or plain attributes (for
        # defensive compatibility with test doubles).
        hooks.add(hook_name)
    return hooks


def _invoke_hook(pm, hook: str, case: FixtureCase, tmp_dir: Path) -> Any:
    ctx = PluginContext(
        run_id=f"contract-{case.plugin_name}-{case.case_name}",
        plugin_name=case.plugin_name,
    )
    spec = case.spec
    options = spec.get("options") or {}
    fixture_dir = case.fixture_dir

    if hook == "source_input":
        input_path = _discover_input_file(fixture_dir, spec.get("input"))
        if input_path is None:
            raise PluginEngineError(
                f"Fixture {fixture_dir} (hook=source_input) has no input.* file"
            )
        return pm.hook.source_input(ctx=ctx, input_path=str(input_path))

    if hook == "asset_type_catalog":
        results = pm.hook.asset_type_catalog(ctx=ctx)
        # Fan-out: the only registered plugin contributes the first list.
        return results[0] if results else None

    if hook == "output":
        portfolio_path = fixture_dir / spec.get("portfolio", "portfolio.json")
        snapshots_path = fixture_dir / spec.get("snapshots", "snapshots.jsonl")
        out_dir = tmp_dir / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        request = OutputRequest(
            portfolio_path=str(portfolio_path),
            snapshots_path=str(snapshots_path),
            output_dir=str(out_dir),
            options=options,
        )
        return pm.hook.output(ctx=ctx, request=request)

    if hook == "state_storage_sync":
        portfolio_path = fixture_dir / spec.get("portfolio", "portfolio.json")
        snapshots_path = fixture_dir / spec.get("snapshots", "snapshots.jsonl")
        db_options = dict(options)
        db_options.setdefault("db_path", str(tmp_dir / "rikdom.duckdb"))
        return pm.hook.state_storage_sync(
            ctx=ctx,
            portfolio_path=str(portfolio_path),
            snapshots_path=str(snapshots_path),
            options=db_options,
        )

    if hook == "state_storage_health":
        health_options = dict(options)
        health_options.setdefault("db_path", str(tmp_dir / "rikdom.duckdb"))
        return pm.hook.state_storage_health(ctx=ctx, options=health_options)

    if hook == "state_storage_query":
        query_name = spec.get("query_name")
        params = spec.get("params") or {}
        return pm.hook.state_storage_query(ctx=ctx, query_name=query_name, params=params)

    if hook in ("observability", "audit_trail"):
        event = spec.get("event", "contract-probe")
        payload = spec.get("payload") or {}
        method = getattr(pm.hook, hook)
        results = method(ctx=ctx, event=event, payload=payload)
        return {"calls": len(results)}

    raise PluginEngineError(f"Unhandled hook: {hook}")


def run_case(case: FixtureCase, plugins_dir: Path, tmp_dir: Path) -> CaseResult:
    import os

    pm, _, _ = _load_plugin(case.plugin_name, plugins_dir)
    env_overrides = case.spec.get("env") or {}
    previous: dict[str, str | None] = {}
    for key, value in env_overrides.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = str(value)
    try:
        payload = _invoke_hook(pm, case.hook, case, tmp_dir)
    except BaseException as exc:  # noqa: BLE001 — contract test captures all
        return CaseResult(error=exc)
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
    normalized = _strip_ignored(payload, set(case.ignore_fields))
    return CaseResult(payload=payload, raw_normalized=_canonical_bytes(normalized))


def validate_schema(payload: Any, alias: str) -> None:
    validator = _load_schema(alias)
    try:
        validator.validate(payload)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise PluginEngineError(
            f"Schema validation failed ({alias}) at {location}: {exc.message}"
        ) from exc


def coverage_report(plugins_dir: str | Path, cases: list[FixtureCase]) -> list[PluginCoverage]:
    """Report hook coverage per plugin under plugins_dir.

    For each plugin we load its class to see which v1 hooks it declares, and
    cross-reference with the set of hooks exercised by discovered fixtures.
    Used by the contract test to fail when a plugin declares a hook but has
    no fixture covering it.
    """
    root = Path(plugins_dir)
    fixtures_by_plugin: dict[str, set[str]] = {}
    for case in cases:
        fixtures_by_plugin.setdefault(case.plugin_name, set()).add(case.hook)

    reports: list[PluginCoverage] = []
    for plugin_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            pm, _manifest, plugin_obj = _load_plugin(plugin_dir.name, root)
        except PluginEngineError:
            continue
        hooks = declared_hooks(plugin_obj)
        # Side-effect hooks are excluded from the coverage requirement because
        # they are fan-out and currently have no in-repo implementations. If a
        # plugin adopts observability/audit_trail it can opt in by adding a
        # fixture — this check only fires when a plugin declares a data hook.
        hooks -= {"observability", "audit_trail"}
        reports.append(
            PluginCoverage(
                plugin_name=plugin_dir.name,
                declared_hooks=hooks,
                covered_hooks=fixtures_by_plugin.get(plugin_dir.name, set()),
            )
        )
    return reports
