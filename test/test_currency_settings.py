import json
import tempfile
import unittest
from pathlib import Path

from core.currency.envirs import ENVIR_NAMES
from core.currency.settings import (
    DEFAULT_EXIT_PLANE,
    EXIT_PLANES,
    PRIORITY_KEYS,
    default_priority,
    load_currency_settings,
    normalize_currency_settings,
    resolve_priority,
    save_currency_settings,
)


class CurrencySettingsTests(unittest.TestCase):
    def test_default_exit_keeps_partial_and_empty_priority_groups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.json"
            path.write_text(
                json.dumps({"prior_exit_plane": None, "priority": {"prior_envir": []}}),
                encoding="utf-8",
            )
            settings = load_currency_settings(path)
        self.assertIsNone(settings["prior_exit_plane"])
        self.assertEqual(settings["priority"]["prior_envir"], [])
        self.assertEqual(settings["priority"]["envir_1"], [])

    def test_partial_saves_preserve_priority_and_exit_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.json"
            priority = default_priority()
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
            path = Path(temp_dir) / "currency.json"
            for entries, expected in cases:
                with self.subTest(entries=entries):
                    priority = {key: entries[:] for key in PRIORITY_KEYS}
                    path.write_text(
                        json.dumps({"priority": priority}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    loaded = load_currency_settings(path)["priority"]
                    self.assertEqual(loaded, {key: expected for key in priority})

    def test_exit_plane_choices_are_fixed(self):
        self.assertEqual(EXIT_PLANES, (1, 2, 3))

    def test_missing_config_uses_first_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_currency_settings(Path(temp_dir) / "missing.json")

        self.assertEqual(settings["exit_after_plane"], DEFAULT_EXIT_PLANE)

    def test_loads_supported_exit_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.json"
            path.write_text(json.dumps({"exit_after_plane": 3}), encoding="utf-8")

            settings = load_currency_settings(path)

        self.assertEqual(settings["exit_after_plane"], 3)

    def test_loads_no_exit_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.json"
            path.write_text(json.dumps({"exit_after_plane": None}), encoding="utf-8")

            settings = load_currency_settings(path)

        self.assertIsNone(settings["exit_after_plane"])

    def test_save_no_exit_plane_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.json"
            path.write_text(json.dumps({"exit_after_plane": 2}), encoding="utf-8")

            saved = save_currency_settings({"exit_after_plane": None}, path)

            self.assertIsNone(saved["exit_after_plane"])
            self.assertIsNone(load_currency_settings(path)["exit_after_plane"])

    def test_invalid_exit_plane_falls_back_to_first_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.json"
            path.write_text(json.dumps({"exit_after_plane": 9}), encoding="utf-8")

            settings = load_currency_settings(path)

        self.assertEqual(settings["exit_after_plane"], DEFAULT_EXIT_PLANE)

    def test_save_preserves_other_currency_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.json"
            path.write_text(json.dumps({"future_setting": True}), encoding="utf-8")

            saved = save_currency_settings({"exit_after_plane": 2}, path)
            values = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(saved["exit_after_plane"], 2)
        self.assertEqual(values, {"future_setting": True, "exit_after_plane": 2})

    def test_deployment_priority_round_trips_and_filters_invalid_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "currency.json"
            save_currency_settings({"deployment": {
                "front_priority": ["character_A", None, "character_B", "character_A", ""],
                "back_priority": "invalid",
            }}, path)
            self.assertEqual(load_currency_settings(path)["deployment"], {
                "front_priority": ["character_A", "character_B"], "back_priority": [], "names": {},
            })
            save_currency_settings({"exit_after_plane": 2}, path)
            self.assertEqual(load_currency_settings(path)["deployment"]["front_priority"], ["character_A", "character_B"])

    def test_deployment_names_are_kept_and_resolved_to_templates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "currency.json"
            save_currency_settings({"deployment": {
                "front_priority": ["三月七", "character_B"],
                "back_priority": ["空名", "", "  "],
                "names": {"character_A": "三月七", "character_C": "空名"},
            }}, path)
            deployment = load_currency_settings(path)["deployment"]
            self.assertEqual(deployment["names"], {"character_A": "三月七", "character_C": "空名"})
            self.assertEqual(resolve_priority(deployment), (
                ["character_A", "character_B"], ["character_C"],
            ))


class CurrencyEnvirTableTest(unittest.TestCase):
    def test_envir_names_cover_current_season(self):
        self.assertEqual(len(ENVIR_NAMES), 72)
        self.assertEqual(len(set(ENVIR_NAMES)), len(ENVIR_NAMES))
        for name in ("蓝海", "银•金•彩", "火药味", "尾彩"):
            self.assertIn(name, ENVIR_NAMES)

    def test_priority_keys_cover_every_envir_level(self):
        self.assertEqual(
            PRIORITY_KEYS,
            ("prior_envir", "envir_1", "envir_2", "envir_3", "envir_4"),
        )
        # 勾选表格按 PRIORITY_KEYS 生成列，两种数据源不能错位
        values = normalize_currency_settings({"priority": {"envir_2": ["蓝海"]}})
        self.assertEqual(values["priority"]["envir_2"], ["蓝海"])
        self.assertEqual(values["priority"]["envir_1"], [])


if __name__ == "__main__":
    unittest.main()
