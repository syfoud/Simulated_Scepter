import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from route import PATHS
from tool import cleanup as cleanup_config
from tool.cleanup import (
    CATEGORIES,
    CleanupConfig,
    CleanupItem,
    load_cleanup_config,
    update_last_cleanup,
)


def make_item(**overrides) -> CleanupItem:
    values = {
        "mode": "manual",
        "trigger": "program_start",
        "value": 3,
        "unit": "day",
        "last_cleanup": "",
    }
    values.update(overrides)
    return CleanupItem(**values)


def write_settings(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=4), encoding="utf-8")


class CleanupConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "app"
        self.path = Path(self.temp_dir.name) / "gui_settings.json"
        self.default_path = self.root / "resource" / "gui_settings_default.json"
        write_settings(
            self.default_path,
            {
                "debug": False,
                "cleanup": {
                    category: {
                        "mode": "manual",
                        "trigger": "program_start",
                        "value": 7,
                        "unit": "day",
                        "last_cleanup": "",
                    }
                    for category in CATEGORIES
                },
            },
        )
        self.addCleanup(patch.stopall)
        patch.dict(PATHS, {"root": str(self.root)}).start()

    def load(self) -> CleanupConfig:
        return load_cleanup_config(self.path)

    def write_cleanup(self, section) -> None:
        write_settings(self.path, {"cleanup": section})

    def test_missing_file_uses_default_values(self):
        config = self.load()

        for category in CATEGORIES:
            item = config.item(category)
            self.assertEqual(item.mode, "manual", category)
            self.assertEqual(item.trigger, "program_start", category)
            self.assertEqual(item.value, 7, category)
            self.assertEqual(item.unit, "day", category)
            self.assertEqual(item.last_cleanup, "", category)

    def test_invalid_parameters_fall_back_one_by_one(self):
        self.write_cleanup(
            {
                "video": {
                    "mode": "automatic",
                    "trigger": "task_end",
                    "value": -10,
                    "unit": "banana",
                    "last_cleanup": "2026-09-24 05:45:00",
                }
            }
        )

        item = self.load().item("video")

        self.assertEqual(item.mode, "automatic")
        self.assertEqual(item.trigger, "task_end")
        self.assertEqual(item.value, 7)
        self.assertEqual(item.unit, "day")
        self.assertEqual(item.last_cleanup, "2026-09-24 05:45:00")

    def test_zero_value_is_valid(self):
        self.write_cleanup({"log": {"value": 0}})

        self.assertEqual(self.load().item("log").value, 0)

    def test_boolean_value_is_invalid(self):
        self.write_cleanup({"log": {"value": True}})

        self.assertEqual(self.load().item("log").value, 7)

    def test_missing_and_mistyped_fields_use_defaults(self):
        self.write_cleanup({"temp": {"mode": "never", "value": 5}})

        item = self.load().item("temp")

        self.assertEqual(item.mode, "never")
        self.assertEqual(item.value, 5)
        self.assertEqual(item.trigger, "program_start")
        self.assertEqual(item.unit, "day")
        self.assertEqual(item.last_cleanup, "")

    def test_invalid_last_cleanup_is_cleared(self):
        for value in ("2026-09-24", "2026-09-24 05:45", "不是时间", 12345, None):
            with self.subTest(value=value):
                self.write_cleanup({"video": {"last_cleanup": value}})
                self.assertEqual(self.load().item("video").last_cleanup, "")

    def test_broken_json_uses_defaults(self):
        self.path.write_text('{"cleanup": {\n', encoding="utf-8")

        config = self.load()

        self.assertEqual(config.item("video").mode, "manual")
        self.assertEqual(config.item("video").value, 7)
        self.assertEqual(config.item("video").last_cleanup, "")

    def test_non_mapping_document_uses_defaults(self):
        write_settings(self.path, ["video", "log"])

        self.assertEqual(self.load().item("video").value, 7)

    def test_cleanup_section_not_mapping_uses_defaults(self):
        write_settings(self.path, {"cleanup": ["video"]})

        self.assertEqual(self.load().item("video").value, 7)

    def test_unreadable_default_keeps_builtin_defaults(self):
        missing_root = Path(self.temp_dir.name) / "missing_app"

        with patch.dict(PATHS, {"root": str(missing_root)}):
            config = load_cleanup_config(self.path)

        self.assertEqual(config.item("video").mode, "manual")
        self.assertEqual(config.item("video").value, 3)
        self.assertEqual(config.item("video").unit, "day")

    def test_update_last_cleanup_keeps_other_parameters(self):
        config = CleanupConfig(items={
            category: make_item(
                mode="periodic",
                trigger="task_end",
                value=2,
                unit="hour",
                last_cleanup="",
            )
            for category in CATEGORIES
        })
        cleanup_config.write_config(config, self.path)
        written = update_last_cleanup("log", "2026-09-24 05:45:00", self.path)
        loaded = load_cleanup_config(self.path)

        self.assertTrue(written)
        self.assertEqual(loaded.item("log").last_cleanup, "2026-09-24 05:45:00")
        self.assertEqual(loaded.item("log").mode, "periodic")
        self.assertEqual(loaded.item("log").trigger, "task_end")
        self.assertEqual(loaded.item("log").value, 2)
        self.assertEqual(loaded.item("log").unit, "hour")
        self.assertEqual(loaded.item("video").last_cleanup, "")

    def test_saved_file_keeps_unified_structure(self):
        config = CleanupConfig(items={name: make_item() for name in CATEGORIES})

        cleanup_config.write_config(config, self.path)
        values = json.loads(self.path.read_text(encoding="utf-8"))

        self.assertEqual(list(values), ["cleanup"])
        self.assertEqual(list(values["cleanup"]), list(CATEGORIES))
        for category in CATEGORIES:
            self.assertEqual(
                list(values["cleanup"][category]),
                ["mode", "trigger", "value", "unit", "last_cleanup"],
            )

    def test_write_keeps_unrelated_settings(self):
        write_settings(
            self.path,
            {
                "debug": True,
                "hotkeys": {"stop": "f8"},
                "cleanup": {category: {} for category in CATEGORIES},
            },
        )

        cleanup_config.write_config(
            CleanupConfig(items={name: make_item() for name in CATEGORIES}), self.path
        )
        values = json.loads(self.path.read_text(encoding="utf-8"))

        self.assertTrue(values["debug"])
        self.assertEqual(values["hotkeys"], {"stop": "f8"})
        self.assertEqual(values["cleanup"]["video"]["value"], 3)


if __name__ == "__main__":
    unittest.main()
