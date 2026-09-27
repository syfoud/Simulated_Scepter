"""不启动游戏依赖，验证模拟宇宙后台线程响应停止并在截图资源关闭前结束。"""

import ast
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock


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


class SimulThreadLifecycleTests(unittest.TestCase):
    def test_start_joins_capture_workers_before_closing_screen(self):
        manager = Mock()
        namespace = {
            "threading": threading,
            "key_mouse_manager": manager,
            "CUS_LOGGER": Mock(),
            "NormalEndError": type("NormalEndError", (Exception,), {}),
            "flush_evidence": Mock(),
            "finish_recovery": Mock(),
        }
        task = load_methods(
            "simul.py", "SimulatedUniverse", {"start", "stop_background_threads"}, namespace
        )
        task._worker_lock = threading.Lock()
        task._show_map = task.record = False
        task.move_thread = task.update_thread = task.map_thread = None
        task._stop = True
        ended = []

        def capture_worker():
            while not task._stop:
                time.sleep(0.001)
            ended.append(True)

        def route():
            task.move_thread = threading.Thread(target=capture_worker)
            task.update_thread = threading.Thread(target=capture_worker)
            task.move_thread.start()
            task.update_thread.start()

        def close_screen():
            self.assertFalse(task.move_thread.is_alive())
            self.assertFalse(task.update_thread.is_alive())
            self.assertEqual(len(ended), 2)

        task.route = route
        task.sct = Mock(close=Mock(side_effect=close_screen))
        task.pos_predictor = Mock()

        task.start()

        manager.stop.assert_called_once()
        task.sct.close.assert_called_once()
        self.assertTrue(task._stop)
        self.assertTrue(task.stop_move)
        self.assertFalse(task.should_update_map)

    def test_stop_returns_while_show_map_is_running(self):
        class MapWorker(threading.Thread):
            # ThreadWithException 默认守护线程；回归失败时也不拖住测试进程
            def __init__(self, **kwargs):
                super().__init__(daemon=True, **kwargs)

        cv = MagicMock()
        cv.pollKey.return_value = -1
        manager = Mock()
        namespace = {
            "threading": threading,
            "time": time,
            "cv": cv,
            "key_mouse_manager": manager,
            "CUS_LOGGER": Mock(),
            "NormalEndError": type("NormalEndError", (Exception,), {}),
            "ThreadWithException": MapWorker,
            "set_forground": Mock(),
            "flush_evidence": Mock(),
            "finish_recovery": Mock(),
        }
        task = load_methods(
            "simul.py", "SimulatedUniverse",
            {"start", "stop", "stop_background_threads", "show_map"}, namespace
        )
        task._worker_lock = threading.Lock()
        task._show_map = True
        task.record = False
        task._stop = True
        task.stop_move = 0
        task.should_update_map = False
        task.move_thread = task.update_thread = task.map_thread = None
        # 地图数据未就绪时 show_map 处于轮询等待分支
        task.debug_map = task.big_map = None
        task.now_loc = task.target_loc = None
        task.sct = Mock()
        task.pos_predictor = Mock()
        task.save_screen = Mock()

        def route():
            while not task._stop:
                time.sleep(0.01)
        task.route = route

        starter = threading.Thread(target=task.start, daemon=True)
        starter.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            worker = task.map_thread
            if worker is not None and worker.is_alive():
                break
            time.sleep(0.01)
        self.assertIsNotNone(task.map_thread)
        self.assertTrue(task.map_thread.is_alive())

        stopper = threading.Thread(target=task.stop, daemon=True)
        stopper.start()
        # show_map 每轮至多休眠 0.1 秒，5 秒上限留有充分余量
        stopper.join(timeout=5)
        stopped_in_time = not stopper.is_alive()
        task._stop = True
        starter.join(timeout=5)

        self.assertTrue(stopped_in_time, "stop() 未在限定时间内返回，show_map 线程可能未轮询停止标志")
        self.assertFalse(starter.is_alive())
        self.assertFalse(task.map_thread.is_alive())
        manager.stop.assert_called()

    def test_ready_wait_returns_when_stop_is_requested(self):
        task = load_methods(
            "tool/simul/utils.py", "UniverseUtils", {"wait_move_ready"}, {"time": time}
        )
        task._stop = False
        task.ready = 0
        task.move_error = None
        task.move_thread = None
        result = []
        waiter = threading.Thread(target=lambda: result.append(task.wait_move_ready()))
        waiter.start()
        task._stop = True
        waiter.join(timeout=1)

        self.assertFalse(waiter.is_alive())
        self.assertEqual(result, [False])

    def test_direction_failure_wakes_waiter_with_cause(self):
        task = load_methods(
            "tool/simul/utils.py", "UniverseUtils",
            {"move_direct_thread", "wait_move_ready"},
            {"time": time, "CUS_LOGGER": Mock()},
        )
        task._stop = False
        task.stop_move = 0
        task.mini_state = 0
        task.ready = 0
        task.move_error = None
        task.move_thread = None
        task.move_direct_to_text = Mock(side_effect=ValueError("识别失败"))

        with self.assertRaisesRegex(ValueError, "识别失败"):
            task.move_direct_thread()
        self.assertEqual(task.ready, 1)
        with self.assertRaisesRegex(RuntimeError, "移动方向识别线程失败") as caught:
            task.wait_move_ready()
        self.assertIs(caught.exception.__cause__, task.move_error)

    def test_updater_resets_running_flag_after_failure(self):
        task = load_methods(
            "tool/simul/utils.py", "UniverseUtils", {"auto_update_map"},
            {"time": time, "CUS_LOGGER": Mock(), "factor": "测试"},
        )
        task.has_update = False
        task.should_update_map = True
        task._stop = False
        task.update_debug_map = Mock(side_effect=RuntimeError("截图失败"))

        with self.assertRaisesRegex(RuntimeError, "截图失败"):
            task.auto_update_map()
        self.assertFalse(task.has_update)

    def test_new_map_phase_waits_for_previous_updater_to_exit(self):
        class NewWorker:
            def __init__(self, **kwargs):
                self.started = False

            def start(self):
                self.started = True

        task = load_methods(
            "tool/simul/utils.py", "UniverseUtils", {"start_map_update"},
            {"ThreadWithException": NewWorker},
        )
        task._worker_lock = threading.Lock()
        task._stop = False
        task.should_update_map = False
        old = Mock()
        old.is_alive.return_value = True
        old.join.side_effect = lambda: setattr(old.is_alive, "return_value", False)
        task.update_thread = old
        task.auto_update_map = Mock()

        task.start_map_update()

        old.join.assert_called_once()
        self.assertTrue(task.should_update_map)
        self.assertIsInstance(task.update_thread, NewWorker)
        self.assertTrue(task.update_thread.started)

    def test_next_move_stops_previous_worker_before_join(self):
        class NewWorker:
            def __init__(self, **kwargs):
                self.started = False

            def start(self):
                self.started = True

        task = load_methods(
            "tool/simul/utils.py", "UniverseUtils", {"start_move_thread"},
            {"ThreadWithException": NewWorker},
        )
        task._worker_lock = threading.Lock()
        task._stop = False
        task.stop_move = 0
        task.ready = 0
        old = Mock()
        old.is_alive.return_value = True
        def finish_previous():
            self.assertEqual(task.stop_move, 1)
            task.ready = 1
        old.join.side_effect = finish_previous
        task.move_thread = old
        task.move_direct_thread = Mock()

        task.start_move_thread(device=1)

        old.join.assert_called_once()
        self.assertEqual(task.stop_move, 0)
        self.assertEqual(task.ready, 0)
        self.assertIsInstance(task.move_thread, NewWorker)
        self.assertTrue(task.move_thread.started)


if __name__ == "__main__":
    unittest.main()
