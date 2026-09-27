"""隔离桌面入口，验证配置与地图备份不依赖启动目录。"""

import ast
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml


class ConfigPathTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "project"
        self.config_dir = self.root / "config" / "config"
        self.config_dir.mkdir(parents=True)
        (self.root / "actions").mkdir()
        (self.root / "actions" / "character.json").write_text("{}", encoding="utf-8")
        self.other = Path(self.directory.name) / "other"
        self.other.mkdir()
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.other)
        self.paths = {"root": str(self.root), "config": str(self.root / "config")}
        self.preferences = {
            "config": {"angle": 1.75, "secondary_fate": ["虚无"]},
            "prior": {"strange": ["项目配置奇物"], "reserved": []},
        }

    def load_class(self, filename, name, methods=None, **globals_):
        source = Path(__file__).resolve().parents[1] / filename
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
        cls.bases = []
        if methods is not None:
            cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
        namespace = {
            "__file__": str(self.root / filename), "PATHS": self.paths, "os": os, "shutil": shutil,
            "sys": sys, "yaml": yaml, "json": json, "CUS_LOGGER": Mock(), **globals_,
        }
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), "exec"), namespace)
        return namespace[name]

    def write_preferences(self, path, data=None):
        path.write_text(yaml.safe_dump(self.preferences if data is None else data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def test_both_modes_read_project_preferences_instead_of_cwd_file(self):
        self.write_preferences(self.config_dir / "info.yml")
        self.write_preferences(self.other / "info.yml", {"prior": {"strange": ["错误目录奇物"]}})
        for source in ("tool/simul/text_key.py", "tool/diver/ocr.py"):
            with self.subTest(source=source):
                keys = self.load_class(source, "text_keys")()
                self.assertIn("项目配置奇物", keys.strange)
                self.assertNotIn("错误目录奇物", keys.strange)
                self.assertEqual(["巡猎", "虚无"], keys.secondary)

    def test_both_modes_copy_missing_preferences_from_project_example(self):
        self.write_preferences(self.config_dir / "info_example.yml")
        target = self.config_dir / "info.yml"
        for source in ("tool/simul/text_key.py", "tool/diver/ocr.py"):
            with self.subTest(source=source):
                keys = self.load_class(source, "text_keys")()
                self.assertIn("项目配置奇物", keys.strange)
                self.assertTrue(target.is_file())
                self.assertFalse((self.other / "info.yml").exists())
                target.unlink()

    def test_frozen_and_source_config_read_and_save_same_project_file(self):
        target = self.config_dir / "info.yml"
        for frozen in (False, True):
            with self.subTest(frozen=frozen), patch.object(sys, "frozen", frozen, create=True):
                self.write_preferences(target)
                settings = self.load_class("tool/diver/config.py", "Config")()
                self.assertEqual("1.75", settings.angle)
                settings.angle = "1.25"
                settings.save()
                self.assertEqual(1.25, yaml.safe_load(target.read_text(encoding="utf-8"))["config"]["angle"])
                self.assertFalse((self.other / "config").exists())

    def test_config_initializes_from_project_example(self):
        self.write_preferences(self.config_dir / "info_example.yml")
        settings = self.load_class("tool/diver/config.py", "Config")()
        self.assertEqual("1.75", settings.angle)
        self.assertTrue((self.config_dir / "info.yml").is_file())

    def test_map_backup_and_restore_share_project_directory(self):
        vision = Mock(IMREAD_GRAYSCALE=0)
        image = object()
        vision.imwrite.side_effect = lambda path, frame: Path(path).write_bytes(b"image")
        vision.imread.return_value = image
        writer = self.load_class("tool/simul/utils.py", "UniverseUtils", {"backup_map"}, cv=vision)()
        writer.big_map = image
        writer.big_map_init = True
        writer.now_loc = [12, 34]
        writer.mini_state = 2
        writer.first_mini = False
        writer.backup_map()
        folder = self.root / "config" / "backup"
        self.assertTrue((folder / "map_attrs_backup.json").is_file())
        vision.imwrite.assert_called_once_with(str(folder / "big_map_backup.png"), image)
        reader = self.load_class("simul.py", "SimulatedUniverse", {"restore_map"}, cv=vision)()
        reader.big_map_init = False
        reader.now_loc = (0, 0)
        reader.mini_state = 0
        reader.first_mini = True
        reader.restore_map()
        vision.imread.assert_called_once_with(str(folder / "big_map_backup.png"), 0)
        self.assertIs(reader.big_map, image)
        self.assertEqual((12, 34), reader.now_loc)
        self.assertEqual(2, reader.mini_state)
        self.assertTrue(reader.big_map_init)
        self.assertFalse(reader.first_mini)
        self.assertFalse((self.other / "config").exists())


if __name__ == "__main__":
    unittest.main()
