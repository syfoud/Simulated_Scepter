"""隔离游戏与桌面依赖，验证自然结束时的资源释放。"""

import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from route import PATHS


def load_task(filename, class_name, methods, namespace):
    """只加载被测业务方法，避免导入时初始化游戏资源。"""
    path = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body
                if isinstance(item, ast.ClassDef) and item.name == class_name)
    node.bases = []
    node.body = [item for item in node.body
                 if isinstance(item, ast.FunctionDef) and item.name in methods]
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[class_name]()


class TaskCompletionTests(unittest.TestCase):
    def setUp(self):
        self.pending = []
        self.executed = []
        self.manager = Mock(running=True)
        self.manager.press.side_effect = self.pending.append
        self.manager.wait.side_effect = self.drain_queue
        self.manager.stop.side_effect = self.stop_manager
        self.namespace = {
            "CUS_LOGGER": Mock(),
            "key_mouse_manager": self.manager,
            "time": SimpleNamespace(sleep=Mock(), time=lambda: 0),
            "os": os,
            "PATHS": PATHS,
        }

    def drain_queue(self):
        self.executed.extend(self.pending)
        self.pending.clear()

    def stop_manager(self):
        self.manager.running = False
        self.pending.clear()

    def test_kernel_stop_releases_shared_input_and_screenshot(self):
        """内核自身停止时停掉键鼠线程、保存收尾截图并放弃地图线程引用。"""
        task = load_task("core/any_fate/utils.py", "FateUtils", {"stop"}, self.namespace)
        task._stop = False
        task.record = False
        task.bveerelbcpgyqan = False
        task.map_thread = object()
        task.save_screen = Mock()

        task.stop()

        self.assertTrue(task._stop)
        self.assertFalse(self.manager.running)
        self.assertIsNone(task.map_thread)
        self.assertEqual(task.save_screen.call_count, 2)

    def test_diver_only_releases_resources_after_final_loading_screen(self):
        """Divergent 只在「加载界面」上结束本局：按两次 esc 退出，然后停止键鼠线程。"""
        for end, screen in [(True, "加载界面"), (False, "加载界面"), (True, "其他界面")]:
            with self.subTest(end=end, screen=screen):
                self.manager.running = True
                self.executed.clear()
                task = load_task("core/divergent/engine.py", "DivergentUniverse", {"loop", "stop"}, self.namespace)
                task.end = end
                task._stop = False
                task.ts = Mock()
                task.get_screen = Mock()
                task.run_static = Mock(return_value=screen)
                task.press = self.executed.append
                task.init_floor = Mock()

                task.loop()

                finished = end and screen == "加载界面"
                self.assertEqual(self.executed, ["esc", "esc"] if finished else [])
                self.assertEqual(bool(task._stop), finished)
                self.assertEqual(self.manager.running, not finished)


if __name__ == "__main__":
    unittest.main()
