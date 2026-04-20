from __future__ import annotations

import unittest

from rikdom.plugins import run_import_plugin


class PluginTests(unittest.TestCase):
    def test_csv_generic_plugin(self) -> None:
        payload = run_import_plugin(
            plugin_name="csv-generic",
            input_path="data/sample_statement.csv",
            plugins_root="plugins/community",
        )
        self.assertEqual(payload["provider"], "csv-generic")
        self.assertEqual(len(payload["holdings"]), 2)


if __name__ == "__main__":
    unittest.main()
