"""差分宇宙移动线程异常退出时，等待方必须在有限时间内被唤醒并拿到失败原因。"""

import ast
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock


def load_methods(filename, class_name, methods, namespace):
    path = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body
                if isinstance(item, ast.ClassDef) and item.name == class_name)
    node.bases = []
    node.body = [item for item in node.body
                 if isinstance(item, ast.FunctionDef) and item.name in methods]
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[class_name]()


class DiverMoveThreadTests(unittest.TestCase):
    def make_task(self):
        task = load_methods(
            "tool/diver/utils.py", "UniverseUtils",
            {"move_thread", "wait_move_ready"}, {"time": time},
        )
        task._stop = False
        task.stop_move = 0
        task.mini_state = 0
        task.ready = 0
        task.move_error = None
        task.is_target = 0
        task.ang_off = 0
        return task

    def test_move_thread_failure_wakes_waiter_with_cause(self):
        task = self.make_task()
        task.move_to_interac = Mock(side_effect=RuntimeError("游戏窗口已失去前台"))
        worker = Mock()
        worker.is_alive.return_value = False

        with self.assertRaisesRegex(RuntimeError, "游戏窗口已失去前台"):
            task.move_thread()
        self.assertEqual(task.ready, 1)
        with self.assertRaisesRegex(RuntimeError, "移动方向识别线程失败") as caught:
            task.wait_move_ready(worker)
        self.assertIs(caught.exception.__cause__, task.move_error)

    def test_waiter_raises_instead_of_hanging_when_worker_fails(self):
        task = self.make_task()
        task.move_to_interac = Mock(side_effect=RuntimeError("游戏窗口已失去前台"))
        worker = threading.Thread(target=task.move_thread, name="差分寻路移动")
        outcome = []

        def wait():
            try:
                task.wait_move_ready(worker)
            except RuntimeError as exc:
                outcome.append(exc)

        waiter = threading.Thread(target=wait)
        worker.start()
        waiter.start()
        worker.join(timeout=5)
        waiter.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertFalse(waiter.is_alive(), "等待移动线程的循环未在有限时间内退出")
        self.assertEqual(len(outcome), 1)
        self.assertIs(outcome[0].__cause__, task.move_error)

    def test_stop_valueerror_stays_silent_and_wakes_waiter(self):
        task = self.make_task()

        def stop_then_raise(*_):
            task._stop = True
            raise ValueError("正在退出")

        task.move_to_interac = Mock(side_effect=stop_then_raise)
        task.move_thread()

        self.assertEqual(task.ready, 1)
        self.assertIsNone(task.move_error)

    def test_waiter_raises_when_worker_exits_before_ready(self):
        task = self.make_task()
        worker = Mock()
        worker.is_alive.return_value = False

        with self.assertRaisesRegex(RuntimeError, "未就绪便已退出"):
            task.wait_move_ready(worker)

    def test_waiter_returns_when_stop_requested(self):
        task = self.make_task()
        worker = Mock()
        worker.is_alive.return_value = True
        result = []
        waiter = threading.Thread(target=lambda: result.append(task.wait_move_ready(worker)))
        waiter.start()
        task._stop = True
        waiter.join(timeout=5)

        self.assertFalse(waiter.is_alive())
        self.assertEqual(result, [False])


if __name__ == "__main__":
    unittest.main()
