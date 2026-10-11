"""配置迁移保留现有值，写入不会覆盖其它模块或未知字段。"""

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
    save_yaml_values,
    write_data,
)


class CoreStorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = copy_core(self.root / "core")
        self.config = self.root / "legacy"
        self.config.mkdir()
        self.enterContext(patch.dict(PATHS, {"core": str(self.core), "config": str(self.config),
                                           "backup": str(self.root / "backup")}))

    def source(self, module):
        return self.core / module / "config.py"

    def test_json_migration_separates_shared_and_private_keys_and_preserves_global_settings(self):
        values = {"debug": True, "hotkeys": {"stop": "f8"}, "early_stop": True,
                  "max_run_time": 9, "silver_wolf_switch": "三号位", "first_plane": 20,
                  "finger_snap_model": {"seed": 123}, "unknown": [1, 2]}
        legacy = self.config / "settings.json"
        legacy.write_text(json.dumps(values), encoding="utf-8")
        common = load_module_settings(self.source("common"))
        iron = load_module_settings(self.source("iron_blood"))
        finger = load_module_settings(self.source("finger_snap"))
        self.assertEqual((common["early_stop"], common["max_run_time"], common["silver_wolf_switch"]), (True, 9, 3))
        self.assertEqual(iron["first_plane"], 20)
        self.assertEqual(finger["finger_snap_model"], {"seed": 123})
        self.assertNotIn("first_plane", common)
        self.assertNotIn("early_stop", iron)
        self.assertEqual(json.loads(legacy.read_text()), {"debug": True, "hotkeys": {"stop": "f8"}, "unknown": [1, 2]})
        backup = self.root / "backup/before_core/settings.json"
        self.assertEqual(json.loads(backup.read_text()), values)

    def test_existing_module_config_wins_and_future_fields_survive_save(self):
        source = self.source("any_fate")
        path = config_path(source)
        path.write_text('{"any_fate": "智识", "future": {"value": 7}}', encoding="utf-8")
        (self.config / "settings.json").write_text('{"any_fate": "巡猎"}', encoding="utf-8")
        self.assertEqual(load_module_settings(source)["any_fate"], "智识")
        save_json_configs([(source, {"any_fate": "丰饶"})])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"any_fate": "丰饶", "future": {"value": 7}})

    def test_yaml_migration_keeps_unknown_values_and_save_merges_config_fields(self):
        source = self.source("simulated")
        (self.config / "info_old.yml").write_text("config:\n  max_run: 8\n  future: 7\ncustom: true\n", encoding="utf-8")
        path = config_path(source)
        save_yaml_values(source, {"config": {"max_run": 10}})
        self.assertIn("future: 7", path.read_text(encoding="utf-8"))
        self.assertIn("custom: true", path.read_text(encoding="utf-8"))
        self.assertIn("max_run: 10", path.read_text(encoding="utf-8"))

    def test_second_file_write_failure_restores_first_file(self):
        one, two = self.source("common"), self.source("any_fate")
        paths = (config_path(one), config_path(two))
        before = [path.read_bytes() for path in paths]

        def fail_second(path, text, *args, **kwargs):
            if path == paths[1]:
                raise OSError("第二个文件无法写入")
            return write_data(path, text)

        with patch("tool.storage.write_data", new=fail_second):
            with self.assertRaises(OSError):
                save_json_configs([(one, {"max_run_time": 7}), (two, {"any_fate": "智识"})])
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_atomic_replace_failure_keeps_existing_config_intact(self):
        path = config_path(self.source("any_fate"))
        original = path.read_bytes()
        with patch("tool.storage.os.replace", side_effect=OSError("替换失败")):
            with self.assertRaises(OSError):
                write_data(path, '{"any_fate": "智识"}')
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob(".config-*")))

    def test_failed_legacy_cleanup_keeps_old_config_and_allows_retry(self):
        legacy = self.config / "settings.json"
        legacy.write_text('{"any_fate": "智识", "debug": true}', encoding="utf-8")
        original = legacy.read_bytes()

        def fail_legacy(path, text):
            if path == legacy:
                raise OSError("旧配置无法更新")
            write_data(path, text)

        with patch("tool.storage.write_data", new=fail_legacy):
            with self.assertRaises(OSError):
                config_path(self.source("any_fate"))
        self.assertEqual(legacy.read_bytes(), original)
        self.assertFalse((self.core / "any_fate/config/settings.json").exists())
        self.assertEqual(load_module_settings(self.source("any_fate"))["any_fate"], "智识")


if __name__ == "__main__":
    unittest.main()
