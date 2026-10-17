"""模块配置缺失字段从默认配置补全，写入不会覆盖未知字段或其它模块。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from route import PATHS
from test.core_fixture import copy_core
from tool.storage import (
    config_path,
    load_module_settings,
    save_json_configs,
    save_json_values,
    write_data,
)


class CoreStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.core = copy_core(self.root / "core")
        self.user = self.root / "user"
        self.user.mkdir()
        self.enterContext(patch.dict(PATHS, {
            "core": str(self.core),
            "user": str(self.user),
            "backup": str(self.root / "backup"),
        }))

    def source(self, module):
        return self.core / module / "config.py"

    def settings_path(self, module):
        return self.user / "core_settings" / f"{module}.json"

    def default_values(self, module):
        path = self.core / module / "config" / "default.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def write_settings(self, module, values):
        path = self.settings_path(module)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        return path

    def test_missing_fields_are_filled_from_default_config(self):
        self.write_settings("simulated", {"config": {"max_run": 8}})

        path = config_path(self.source("simulated"))
        values = json.loads(path.read_text(encoding="utf-8"))
        defaults = self.default_values("simulated")

        self.assertEqual(values["config"]["max_run"], 8)
        self.assertEqual(values["config"]["fate"], defaults["config"]["fate"])
        self.assertEqual(values["config"]["order_text"], defaults["config"]["order_text"])
        self.assertEqual(values["prior"], defaults["prior"])
        self.assertEqual(values["key_mapping"], defaults["key_mapping"])

    def test_existing_values_win_over_default_config(self):
        self.write_settings("simulated", {"config": {"fate": "虚无"}})

        values = load_module_settings(self.source("simulated"))
        defaults = self.default_values("simulated")

        self.assertEqual(values["config"]["fate"], "虚无")
        self.assertEqual(values["config"]["order_text"], defaults["config"]["order_text"])

    def test_existing_module_config_wins_and_future_fields_survive_save(self):
        self.write_settings("any_fate", {"any_fate": "智识", "future": {"value": 7}})

        self.assertEqual(load_module_settings(self.source("any_fate"))["any_fate"], "智识")
        save_json_configs([(self.source("any_fate"), {"any_fate": "丰饶"})])

        values = json.loads(self.settings_path("any_fate").read_text(encoding="utf-8"))
        self.assertEqual(values["any_fate"], "丰饶")
        self.assertEqual(values["future"], {"value": 7})

    def test_save_json_values_keeps_unknown_values_and_merges_config_fields(self):
        self.write_settings("simulated", {"config": {"max_run": 8, "future": 7}, "custom": True})

        save_json_values(self.source("simulated"), {"config": {"max_run": 10}})

        values = json.loads(self.settings_path("simulated").read_text(encoding="utf-8"))
        self.assertEqual(values["config"]["max_run"], 10)
        self.assertEqual(values["config"]["future"], 7)
        self.assertIs(values["custom"], True)
        self.assertEqual(values["config"]["fate"], self.default_values("simulated")["config"]["fate"])

    def test_second_file_write_failure_restores_first_file(self):
        first = config_path(self.source("common"))
        second = config_path(self.source("any_fate"))
        before = {first: first.read_bytes(), second: second.read_bytes()}

        original_write_data = write_data

        def fail_second(path, text):
            if Path(path) == second:
                raise OSError("第二个文件无法写入")
            return original_write_data(path, text)

        with patch("tool.storage.write_data", side_effect=fail_second):
            with self.assertRaises(OSError):
                save_json_configs([
                    (self.source("common"), {"max_run_time": 7}),
                    (self.source("any_fate"), {"any_fate": "智识"}),
                ])

        self.assertEqual(first.read_bytes(), before[first])
        self.assertEqual(second.read_bytes(), before[second])

    def test_atomic_replace_failure_keeps_existing_config_intact(self):
        path = self.root / "settings.json"
        path.write_text('{"any_fate": "丰饶"}', encoding="utf-8")

        with patch("tool.storage.os.replace", side_effect=OSError("替换失败")):
            with self.assertRaises(OSError):
                write_data(path, '{"any_fate": "智识"}')

        self.assertEqual(path.read_text(encoding="utf-8"), '{"any_fate": "丰饶"}')
        self.assertFalse(list(path.parent.glob(".config-*")))


if __name__ == "__main__":
    unittest.main()
