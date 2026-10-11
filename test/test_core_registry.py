"""验证目录发现、按需导入、继承依赖以及删除模块后的隔离。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core
from tool.registry import KernelRegistry


class KernelRegistryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.enterContext(patch.object(core, "__path__", [str(self.root)]))
        self.addCleanup(self.clear_modules)

    def clear_modules(self):
        for name in list(sys.modules):
            if name.startswith("core.probe_"):
                del sys.modules[name]

    def module(self, folder, parent="", *, runnable=True, body=None):
        directory = self.root / folder
        directory.mkdir()
        (directory / "__init__.py").write_text("", encoding="utf-8")
        if body is None:
            body = (f"from core.{parent}.engine import Kernel as Parent\n" if parent else "")
            body += f"class Kernel({'Parent' if parent else 'object'}):\n    pass\n"
            body += "def create_engine(*, script=False):\n    return Kernel()\n"
            body += "def create_settings(parent=None):\n    return ('settings', parent)\n"
        (directory / "engine.py").write_text(body, encoding="utf-8")
        (directory / "settings.py").write_text("def create_settings(parent=None): return ('settings', parent)\n", encoding="utf-8")
        (directory / "module.ini").write_text(
            f"[module]\nid={folder}\nname={folder}\ndescription=测试内核\n"
            f"parent={parent}\nentry=engine:Kernel\n"
            + ("factory=engine:create_engine\nsettings=settings:create_settings\nbutton=运行\n" if runnable else ""),
            encoding="utf-8",
        )
        return directory

    def test_discovery_does_not_import_python_and_settings_do_not_load_other_engines(self):
        self.module("probe_base", runnable=False)
        self.module("probe_child", "probe_base")
        self.module("probe_other")
        registry = KernelRegistry(self.root)
        self.assertNotIn("core.probe_child.engine", sys.modules)
        self.assertEqual(len(registry.runnable()), 2)
        self.assertEqual(registry.create_settings("probe_child", "parent"), ("settings", "parent"))
        self.assertNotIn("core.probe_base.engine", sys.modules)
        self.assertNotIn("core.probe_other.engine", sys.modules)

    def test_removing_leaf_does_not_affect_sibling_loading(self):
        self.module("probe_base", runnable=False)
        leaf = self.module("probe_leaf", "probe_base")
        self.module("probe_sibling", "probe_base")
        # 从发现目录移走叶子，且让导入系统无法找到它。
        leaf.rename(self.root / "removed")
        (self.root / "removed/module.ini").unlink()
        registry = KernelRegistry(self.root)
        self.assertEqual([spec.id for spec in registry.runnable()], ["probe_sibling"])
        sibling = registry.create_engine("probe_sibling")
        self.assertIsInstance(sibling, registry.load_class("probe_base"))
        self.assertNotIn("core.probe_leaf.engine", sys.modules)
        self.assertFalse(registry.errors)

    def test_missing_parent_disables_descendants_and_keeps_independent_module(self):
        self.module("probe_child", "probe_missing")
        self.module("probe_grandchild", "probe_child")
        self.module("probe_other")
        registry = KernelRegistry(self.root)
        self.assertEqual([spec.id for spec in registry.runnable()], ["probe_other"])
        self.assertIn("缺少父内核", registry.errors["probe_child"])
        self.assertIn("缺少父内核", registry.errors["probe_grandchild"])
        self.assertIsNotNone(registry.create_engine("probe_other"))

    def test_cycle_and_broken_ini_are_reported_without_blocking_independent_module(self):
        self.module("probe_one", "probe_two")
        self.module("probe_two", "probe_one")
        broken = self.module("probe_bad")
        (broken / "module.ini").write_text("[module\n", encoding="utf-8")
        self.module("probe_other")
        registry = KernelRegistry(self.root)
        self.assertEqual([spec.id for spec in registry.runnable()], ["probe_other"])
        self.assertEqual(len(registry.errors), 3)
        self.assertIsNotNone(registry.create_engine("probe_other"))

    def test_descriptor_inheritance_and_factory_return_type_are_validated(self):
        self.module("probe_base", runnable=False)
        self.module("probe_bad", "probe_base", body="class Kernel: pass\n")
        self.module("probe_wrong", body="class Kernel: pass\ndef create_engine(*, script=False): return object()\n")
        registry = KernelRegistry(self.root)
        with self.assertRaisesRegex(ValueError, "继承关系不一致"):
            registry.create_engine("probe_bad")
        with self.assertRaisesRegex(TypeError, "错误的内核类型"):
            registry.create_engine("probe_wrong")

    def test_new_module_adds_entry_without_frontend_change(self):
        self.module("probe_first")
        self.assertEqual(len(KernelRegistry(self.root).runnable()), 1)
        self.module("probe_second")
        registry = KernelRegistry(self.root)
        self.assertEqual(len(registry.runnable()), 2)
        self.assertIsNotNone(registry.create_engine("probe_second", script=True))

    def test_duplicate_id_disables_ambiguous_parent_and_its_children(self):
        self.module("probe_base", runnable=False)
        second = self.module("probe_duplicate", runnable=False)
        path = second / "module.ini"
        path.write_text(path.read_text(encoding="utf-8").replace("id=probe_duplicate", "id=probe_base"), encoding="utf-8")
        self.module("probe_child", "probe_base")
        self.module("probe_other")
        registry = KernelRegistry(self.root)
        self.assertEqual([spec.id for spec in registry.runnable()], ["probe_other"])
        self.assertIn("重复", registry.errors["probe_base"])
        self.assertIn("缺少父内核", registry.errors["probe_child"])


if __name__ == "__main__":
    unittest.main()
