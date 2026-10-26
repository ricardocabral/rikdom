from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from rikdom.cli import main
from rikdom.plugin_engine import pipeline
from rikdom.plugin_engine.contract_runner import discover_fixtures, run_case
from rikdom.plugin_engine.errors import PluginEngineError, PluginTypeError


class ConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugins = self.root / "plugins"
        for name, transport in (("test-rest", "rest"), ("test-mcp", "mcp")):
            folder = self.plugins / name
            folder.mkdir(parents=True)
            (folder / "plugin.json").write_text(json.dumps({
                "name": name, "version": "0.1.0", "api_version": "1.1",
                "plugin_types": ["external/connector"], "module": "plugin", "class_name": "Plugin",
            }))
            self.write_plugin(name, transport=transport)

    def write_plugin(self, name="test-rest", *, transport="rest", description=None, query=None):
        description = description if description is not None else {
            "contractVersion": "1.0", "readOnly": True, "transport": transport,
            "operations": {"lookup": {}},
        }
        query = query or "return {'operation': operation, 'params': params, 'plugin': ctx.plugin_name}"
        (self.plugins / name / "plugin.py").write_text(
            "from rikdom.plugin_engine.hookspecs import hookimpl\n"
            "class Plugin:\n"
            "    @hookimpl\n"
            "    def connector_describe(self, ctx):\n"
            f"        return {description!r}\n"
            "    @hookimpl\n"
            "    def connector_query(self, ctx, operation, params):\n"
            f"        {query}\n"
        )

    def test_queries_selected_connector_without_assuming_protocol_or_provider(self) -> None:
        for name in ("test-rest", "test-mcp"):
            with self.subTest(plugin=name):
                result = pipeline.run_connector_query_pipeline(
                    name, str(self.plugins), "lookup", {"ids": ["a", "b"], "optional": None}
                )
                self.assertEqual(result["data"], {
                    "operation": "lookup", "params": {"ids": ["a", "b"], "optional": None}, "plugin": name,
                })
                self.assertEqual(result["contractVersion"], "1.0")
                self.assertEqual(result["plugin"], {"name": name, "version": "0.1.0", "apiVersion": "1.1"})
                self.assertEqual(result["operation"], "lookup")
                self.assertIsNotNone(datetime.fromisoformat(result["retrievedAt"]).utcoffset())
                self.assertNotIn("params", result)

    def test_describes_connector_without_making_query(self) -> None:
        self.write_plugin(query="raise AssertionError('query must not run')")
        self.assertEqual(
            pipeline.run_connector_describe_pipeline("test-rest", str(self.plugins)),
            {"contractVersion": "1.0", "readOnly": True, "transport": "rest", "operations": {"lookup": {}}},
        )

    def test_only_selected_plugin_code_is_loaded(self) -> None:
        (self.plugins / "test-mcp" / "plugin.py").write_text("raise AssertionError('unselected plugin loaded')")
        pipeline.run_connector_query_pipeline("test-rest", str(self.plugins), "lookup", {})

    def test_query_cannot_mutate_callers_nested_parameters(self) -> None:
        self.write_plugin(query="params['ids'].append('mutated'); return params")
        params = {"ids": ["original"]}
        result = pipeline.run_connector_query_pipeline("test-rest", str(self.plugins), "lookup", params)
        self.assertEqual(params, {"ids": ["original"]})
        self.assertEqual(result["data"], {"ids": ["original", "mutated"]})

    def test_result_metadata_cannot_be_overwritten_by_provider_fields(self) -> None:
        self.write_plugin(query="return {'plugin': 'forged', 'retrievedAt': 'yesterday', 'value': None}")
        result = pipeline.run_connector_query_pipeline("test-rest", str(self.plugins), "lookup", {})
        self.assertEqual(result["plugin"]["name"], "test-rest")
        self.assertEqual(result["data"]["plugin"], "forged")
        self.assertIsNone(result["data"]["value"])
        self.assertNotEqual(result["retrievedAt"], "yesterday")

    def test_rejects_invalid_json_parameters_before_loading_plugin(self) -> None:
        cyclic = {}
        cyclic["cycle"] = cyclic
        for params in ([], {"a": float("nan")}, {"a": float("inf")}, {1: "key"}, {"a": (1, 2)}, {"a": object()}, cyclic):
            with self.subTest(params_type=type(params).__name__):
                with patch.object(pipeline, "_load_single_plugin_manager") as loader:
                    with self.assertRaises(PluginEngineError):
                        pipeline.run_connector_query_pipeline("test-rest", str(self.plugins), "lookup", params)
                    loader.assert_not_called()

    def test_rejects_non_json_and_non_object_results(self) -> None:
        for expression in ("[]", "{'value': float('nan')}", "{'value': object()}", "{1: 'key'}"):
            with self.subTest(expression=expression):
                self.write_plugin(query=f"return {expression}")
                with self.assertRaises(PluginEngineError):
                    pipeline.run_connector_query_pipeline("test-rest", str(self.plugins), "lookup", {})

    def test_rejects_invalid_capabilities_before_query(self) -> None:
        valid = {"contractVersion": "1.0", "readOnly": True, "operations": {"lookup": {}}}
        for description in ({}, {**valid, "contractVersion": "2.0"}, {**valid, "readOnly": False},
                            {**valid, "operations": ["lookup"]}, {**valid, "operations": {"lookup": None}},
                            {**valid, "operations": {}}, {**valid, "operations": {" ": {}}}):
            with self.subTest(description=description):
                self.write_plugin(description=description, query="raise AssertionError('query must not run')")
                with self.assertRaises(PluginEngineError):
                    pipeline.run_connector_query_pipeline("test-rest", str(self.plugins), "lookup", {})

    def test_undeclared_operation_is_rejected_before_query(self) -> None:
        self.write_plugin(query="raise AssertionError('query must not run')")
        with self.assertRaisesRegex(PluginEngineError, "does not declare operation"):
            pipeline.run_connector_query_pipeline("test-rest", str(self.plugins), "undeclared", {})

    def test_rejects_plugin_with_wrong_type(self) -> None:
        path = self.plugins / "test-rest" / "plugin.json"
        manifest = json.loads(path.read_text())
        manifest["plugin_types"] = ["source/input"]
        path.write_text(json.dumps(manifest))
        with self.assertRaises(PluginTypeError):
            pipeline.run_connector_describe_pipeline("test-rest", str(self.plugins))

    def test_cli_query_returns_json_and_does_not_create_workspace_files(self) -> None:
        output, error = io.StringIO(), io.StringIO()
        before = os.getcwd()
        try:
            os.chdir(self.root)
            with redirect_stdout(output), redirect_stderr(error):
                result = main([
                    "connector", "query", "--plugin", "test-mcp", "--plugins-dir", str(self.plugins),
                    "--operation", "lookup", "--params", '{"ids":["a","b"],"optional":null}',
                ])
            self.assertEqual(result, 0, error.getvalue())
            self.assertEqual(json.loads(output.getvalue())["data"], {
                "operation": "lookup", "params": {"ids": ["a", "b"], "optional": None}, "plugin": "test-mcp",
            })
            self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["plugins"])
        finally:
            os.chdir(before)

    def test_cli_describe_selects_requested_connector(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["connector", "describe", "--plugin", "test-rest", "--plugins-dir", str(self.plugins)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["transport"], "rest")

    def test_cli_rejects_invalid_parameters_without_traceback(self) -> None:
        for params in ("not-json", "[]", "null", '{"value":NaN}', '{"value":Infinity}'):
            with self.subTest(params=params):
                output, error = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    result = main([
                        "connector", "query", "--plugin", "test-rest", "--plugins-dir", str(self.plugins),
                        "--operation", "lookup", "--params", params,
                    ])
                self.assertEqual(result, 1)
                self.assertEqual(output.getvalue(), "")
                self.assertNotIn("Traceback", error.getvalue())

    def test_cli_missing_plugin_is_actionable(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            result = main(["connector", "describe", "--plugin", "missing", "--plugins-dir", str(self.plugins)])
        self.assertEqual(result, 1)
        self.assertIn("missing", error.getvalue())

    def test_offline_query_fixture_uses_same_validation_and_preserves_raw_data(self) -> None:
        folder = self.plugins / "test-rest" / "fixtures" / "query"
        folder.mkdir(parents=True)
        (folder / "case.json").write_text(json.dumps({"hook": "connector_query", "operation": "lookup", "params": {"id": "one"}}))
        (folder / "expected.json").write_text("{}")
        case = discover_fixtures(self.plugins)[0]
        result = run_case(case, self.plugins, self.root)
        self.assertIsNone(result.error)
        self.assertEqual(result.payload, {"operation": "lookup", "params": {"id": "one"}, "plugin": "test-rest"})
        self.write_plugin(description={})
        result = run_case(case, self.plugins, self.root)
        self.assertIsInstance(result.error, PluginEngineError)


if __name__ == "__main__":
    unittest.main()
