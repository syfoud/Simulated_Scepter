import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

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


def write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")

class CleanupConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "cleanup_config.yml"
        self.example_path = Path(self.temp_dir.name) / "cleanup_config_example.yml"
        write_yaml(
            self.example_path,
            "video:\n"
            "  mode: manual\n"
            "  trigger: program_start\n"
            "  value: 7\n"
            "  unit: day\n"
            "  last_cleanup: \"\"\n"
            "log:\n"
            "  mode: manual\n"
            "  trigger: program_start\n"
            "  value: 7\n"
            "  unit: day\n"
            "  last_cleanup: \"\"\n"
            "temp:\n"
            "  mode: manual\n"
            "  trigger: program_start\n"
            "  value: 7\n"
            "  unit: day\n"
            "  last_cleanup: \"\"\n",
        )

    def load(self):
        with patch.object(cleanup_config, "EXAMPLE_PATH", str(self.example_path)):
            return load_cleanup_config(self.path)

    def test_missing_file_uses_example_defaults(self):
        config = self.load()

        for category in CATEGORIES:
            item = config.item(category)
            self.assertEqual(item.mode, "manual", category)
            self.assertEqual(item.trigger, "program_start", category)
            self.assertEqual(item.value, 7, category)
            self.assertEqual(item.unit, "day", category)
            self.assertEqual(item.last_cleanup, "", category)

    def test_invalid_parameters_fall_back_one_by_one(self):
        write_yaml(
            self.path,
            "video:\n"
            "  mode: automatic\n"
            "  trigger: task_end\n"
            "  value: -10\n"
            "  unit: banana\n"
            "  last_cleanup: \"2026-09-24 05:45:00\"\n",
        )

        item = self.load().item("video")

        self.assertEqual(item.mode, "automatic")
        self.assertEqual(item.trigger, "task_end")
        self.assertEqual(item.value, 7)
        self.assertEqual(item.unit, "day")
        self.assertEqual(item.last_cleanup, "2026-09-24 05:45:00")

    def test_zero_value_is_valid(self):
        write_yaml(self.path, "log:\n  value: 0\n")

        self.assertEqual(self.load().item("log").value, 0)

    def test_boolean_value_is_invalid(self):
        write_yaml(self.path, "log:\n  value: true\n")

        self.assertEqual(self.load().item("log").value, 7)

    def test_missing_and_mistyped_fields_use_defaults(self):
        write_yaml(self.path, "temp:\n  mode: never\n  value: 5\n")

        item = self.load().item("temp")

        self.assertEqual(item.mode, "never")
        self.assertEqual(item.value, 5)
        self.assertEqual(item.trigger, "program_start")
        self.assertEqual(item.unit, "day")
        self.assertEqual(item.last_cleanup, "")

    def test_invalid_last_cleanup_is_cleared(self):
        for value in ("2026-09-24", "2026-09-24 05:45", "不是时间", 12345, None):
            with self.subTest(value=value):
                write_yaml(self.path, f"video:\n  last_cleanup: {value!r}\n")
                self.assertEqual(self.load().item("video").last_cleanup, "")

    def test_broken_yaml_uses_example_for_every_field(self):
        write_yaml(self.path, "video: [\n")

        item = self.load().item("video")

        self.assertEqual(item.mode, "manual")
        self.assertEqual(item.value, 7)
        self.assertEqual(item.last_cleanup, "")

    def test_non_mapping_document_uses_example(self):
        write_yaml(self.path, "- video\n- log\n")

        self.assertEqual(self.load().item("video").value, 7)

    def test_unreadable_example_keeps_builtin_defaults(self):
        broken_example = Path(self.temp_dir.name) / "missing_example.yml"

        with patch.object(cleanup_config, "EXAMPLE_PATH", str(broken_example)):
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
        with patch.object(cleanup_config, "EXAMPLE_PATH", str(self.example_path)):
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
        values = yaml.safe_load(self.path.read_text(encoding="utf-8"))

        self.assertEqual(list(values), list(CATEGORIES))
        for category in CATEGORIES:
            self.assertEqual(
                list(values[category]),
                ["mode", "trigger", "value", "unit", "last_cleanup"],
            )


if __name__ == "__main__":
    unittest.main()
