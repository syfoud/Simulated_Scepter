import tempfile
import unittest
from pathlib import Path

import yaml

from tool.currency.settings import (
    DEFAULT_EXIT_PLANE,
    EXIT_PLANES,
    load_currency_settings,
    load_default_priority,
    save_currency_settings,
)


class CurrencySettingsTests(unittest.TestCase):
    def test_default_exit_keeps_partial_and_empty_priority_groups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            path.write_text(
                "prior_exit_plane: null\npriority:\n  prior_envir: []\n",
                encoding="utf-8",
            )
            settings = load_currency_settings(path)
        self.assertIsNone(settings["prior_exit_plane"])
        self.assertEqual(settings["priority"]["prior_envir"], [])
        self.assertEqual(settings["priority"]["envir_1"], load_default_priority()["envir_1"])

    def test_partial_saves_preserve_priority_and_exit_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            priority = load_default_priority()
            priority["prior_envir"] = ["蓝海"]
            save_currency_settings({"priority": priority, "exit_after_plane": 2}, path)
            save_currency_settings({"exit_after_plane": 3}, path)
            self.assertEqual(load_currency_settings(path)["priority"], priority)
            priority["prior_envir"] = []
            save_currency_settings({"priority": priority}, path)
            self.assertEqual(load_currency_settings(path)["exit_after_plane"], 3)
            self.assertEqual(load_currency_settings(path)["priority"]["prior_envir"], [])

    def test_priority_filters_non_string_entries_and_keeps_order(self):
        cases = [
            ([42, "蓝海", None, True, {}, [], "黄金时代"], ["蓝海", "黄金时代"]),
            ([42, None], []),
            ([], []),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            for entries, expected in cases:
                with self.subTest(entries=entries):
                    priority = {key: entries[:] for key in load_default_priority()}
                    path.write_text(
                        yaml.safe_dump({"priority": priority}, allow_unicode=True),
                        encoding="utf-8",
                    )
                    loaded = load_currency_settings(path)["priority"]
                    self.assertEqual(loaded, {key: expected for key in priority})

    def test_exit_plane_choices_are_fixed(self):
        self.assertEqual(EXIT_PLANES, (1, 2, 3))

    def test_missing_config_uses_first_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_currency_settings(Path(temp_dir) / "missing.yml")

        self.assertEqual(settings["exit_after_plane"], DEFAULT_EXIT_PLANE)

    def test_loads_supported_exit_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            path.write_text("exit_after_plane: 3\n", encoding="utf-8")

            settings = load_currency_settings(path)

        self.assertEqual(settings["exit_after_plane"], 3)

    def test_invalid_exit_plane_falls_back_to_first_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            path.write_text("exit_after_plane: 9\n", encoding="utf-8")

            settings = load_currency_settings(path)

        self.assertEqual(settings["exit_after_plane"], DEFAULT_EXIT_PLANE)

    def test_save_preserves_other_currency_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            path.write_text("future_setting: true\n", encoding="utf-8")

            saved = save_currency_settings({"exit_after_plane": 2}, path)
            values = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(saved["exit_after_plane"], 2)
        self.assertEqual(values, {"future_setting": True, "exit_after_plane": 2})


if __name__ == "__main__":
    unittest.main()
