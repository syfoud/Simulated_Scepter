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
        self.recorder = Mock(recording=True)
        self.recorder.stop_recording.side_effect = lambda: setattr(self.recorder, "recording", False)
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

    def test_simul_completion_finishes_exit_action_and_releases_resources(self):
        task = load_task("core/simulated/engine.py", "SimulatedUniverse", {"re_init", "stop"}, self.namespace)
        task.end = task.record = task.bveerelbcpgyqan = True
        task._stop = False
        task.recorder = self.recorder
        task.save_screen = Mock()

        self.assertEqual(task.re_init(), 1)

        self.assertEqual(self.executed, ["esc"])
        self.assertTrue(task._stop)
        self.assertFalse(self.manager.running)
        self.assertFalse(self.recorder.recording)

    def test_simul_next_round_keeps_resources_running(self):
        task = load_task("core/simulated/engine.py", "SimulatedUniverse", {"re_init", "stop"}, self.namespace)
        task.end = False
        task.init_map = Mock()

        task.re_init()

        self.assertTrue(self.manager.running)
        self.assertTrue(self.recorder.recording)

    def test_diver_only_releases_resources_after_final_loading_screen(self):
        for end, screen in [(True, "加载界面"), (False, "加载界面"), (True, "其他界面")]:
            with self.subTest(end=end, screen=screen):
                self.manager.running = self.recorder.recording = True
                self.executed.clear()
                task = load_task("core/divergent/engine.py", "DivergentUniverse", {"loop", "stop"}, self.namespace)
                task.end = end
                task.record = task._u1a = True
                task._stop = False
                task.ts = Mock()
                task.get_screen = Mock()
                task.run_static = Mock(return_value=screen)
                task.press = self.executed.append
                task.init_floor = Mock()
                task.recorder = self.recorder

                task.loop()

                finished = end and screen == "加载界面"
                self.assertEqual(self.executed, ["esc", "esc"] if finished else [])
                self.assertEqual(bool(task._stop), finished)
                self.assertEqual(self.manager.running, not finished)
                self.assertEqual(self.recorder.recording, not finished)


if __name__ == "__main__":
    unittest.main()
