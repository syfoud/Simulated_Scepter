"""按键操作失败或任务停止时，不留下持续按下的移动键。"""

import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def load_key_mouse_manager():
    events = []
    pyautogui = types.ModuleType("pyautogui")
    pyautogui.keyDown = lambda key: events.append(("down", key))
    pyautogui.keyUp = lambda key: events.append(("up", key))
    pyautogui.mouseUp = Mock()
    logger = types.ModuleType("tool.log")
    logger.CUS_LOGGER = Mock()
    thread = types.ModuleType("tool.thread")
    thread.ThreadWithException = threading.Thread
    imports = {
        "pyautogui": pyautogui,
        "win32api": types.ModuleType("win32api"),
        "win32con": types.ModuleType("win32con"),
        "tool.log": logger,
        "tool.thread": thread,
    }
    source = Path(__file__).resolve().parents[1] / "tool" / "key_mouse_manager.py"
    spec = importlib.util.spec_from_file_location("_key_mouse_manager_test", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, imports):
        spec.loader.exec_module(module)
    return module.KeyMouseManager, events, logger


class KeyReleaseTests(unittest.TestCase):
    def test_wait_returns_for_newly_started_empty_queue(self):
        manager_class, _, logger = load_key_mouse_manager()
        manager = manager_class()
        with patch.dict(sys.modules, {"tool.log": logger}):
            manager.start()
            waiter = threading.Thread(target=manager.wait, daemon=True)
            try:
                waiter.start()
                waiter.join(1)
                self.assertFalse(waiter.is_alive())
            finally:
                manager.stop()

    def test_clean_waits_for_key_registration_and_releases_it(self):
        manager_class, events, logger = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        entered, resume = threading.Event(), threading.Event()
        pyautogui = manager_class.clean.__globals__["pyautogui"]

        def key_down(key):
            events.append(("down", key))
            entered.set()
            if not resume.wait(2):
                raise TimeoutError("未释放模拟按键等待")

        pyautogui.keyDown = key_down
        with patch.dict(sys.modules, {"tool.log": logger}):
            worker = threading.Thread(target=manager._execute_operation,
                                      args=({"type": "keyDown", "key": "w"},))
            cleaner = threading.Thread(target=manager.clean)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                cleaner.start()
            finally:
                resume.set()
                worker.join(2)
                cleaner.join(2)
            self.assertFalse(worker.is_alive())
            self.assertFalse(cleaner.is_alive())
        self.assertEqual(events, [("down", "w"), ("up", "w")])
        self.assertFalse(manager.pressed_keys)

    def test_clean_invalidates_already_dequeued_operation(self):
        manager_class, events, _ = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        generation = manager.input_generation
        manager.clean()
        manager._execute_operation({"type": "keyDown", "key": "w"}, generation)
        self.assertEqual(events, [])

    def test_clean_discards_old_sleep_before_forced_release(self):
        manager_class, _, _ = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        manager.sleep_start_time = manager_class._sleep.__globals__["time"].time()
        manager.sleep_duration = 30
        manager.clean()
        manager.keyUp("w", force=True)
        self.assertEqual([item["type"] for item in manager.operation_queue], ["keyUp"])

    def test_turn_stops_after_current_segment(self):
        for cancel in ("stop", "clean"):
            with self.subTest(cancel=cancel):
                manager_class, _, _ = load_key_mouse_manager()
                manager = manager_class()
                manager.running = True
                namespace = manager_class._direct_mouse_move.__globals__
                namespace["win32con"].MOUSEEVENTF_MOVE = 1
                namespace["win32api"].mouse_event = Mock()
                manager._sleep = lambda *_: getattr(manager, cancel)()
                manager._direct_mouse_move(90)
                namespace["win32api"].mouse_event.assert_called_once()

    def test_stop_during_drag_delay_never_starts_drag(self):
        manager_class, _, _ = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        namespace = manager_class._execute_operation.__globals__
        namespace["win32api"].SetCursorPos = Mock()
        namespace["pyautogui"].dragTo = Mock()
        manager._sleep = lambda *_: manager.stop()
        manager._execute_operation({"type": "drag", "start_x": 1, "start_y": 2,
                                    "end_x": 3, "end_y": 4})
        namespace["pyautogui"].dragTo.assert_not_called()

    def test_wait_does_not_return_while_operation_is_in_progress(self):
        manager_class, _, logger = load_key_mouse_manager()
        manager = manager_class()
        entered, resume, waited = threading.Event(), threading.Event(), threading.Event()

        def execute(*_):
            entered.set()
            if not resume.wait(2):
                raise TimeoutError("未释放模拟操作等待")

        manager._execute_operation = execute
        with patch.dict(sys.modules, {"tool.log": logger}):
            manager.start()
            manager.keyDown("w")
            waiter = threading.Thread(target=lambda: (manager.wait(), waited.set()))
            try:
                self.assertTrue(entered.wait(1))
                waiter.start()
                self.assertFalse(waited.wait(0.05))
            finally:
                resume.set()
                waiter.join(2)
                manager.stop()
        self.assertTrue(waited.is_set())

    def test_worker_failure_releases_previously_held_keys(self):
        manager_class, events, logger = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        namespace = manager_class._execute_operation.__globals__
        namespace["win32api"].SetCursorPos = Mock(side_effect=RuntimeError("cursor failed"))
        manager.operation_queue.extend([
            {"type": "keyDown", "key": "w"},
            {"type": "click", "x": 1, "y": 2},
        ])
        with patch.dict(sys.modules, {"tool.log": logger}):
            with self.assertRaisesRegex(RuntimeError, "cursor failed"):
                manager._worker()
        self.assertEqual(events, [("down", "w"), ("up", "w")])
        self.assertFalse(manager.pressed_keys)

    def test_press_releases_key_when_sleep_fails(self):
        manager_class, events, logger = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        manager._sleep = Mock(side_effect=RuntimeError("interrupted"))

        with patch.dict(sys.modules, {"tool.log": logger}), self.assertRaisesRegex(RuntimeError, "interrupted"):
            manager._execute_operation({"type": "press", "key": "w", "duration": 1})

        self.assertEqual(events, [("down", "w"), ("up", "w")])
        self.assertFalse(manager.pressed_keys)

    def test_stop_releases_held_key(self):
        manager_class, events, logger = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        with patch.dict(sys.modules, {"tool.log": logger}):
            manager._execute_operation({"type": "keyDown", "key": "w"})
            manager.stop()

        self.assertEqual(events, [("down", "w"), ("up", "w")])
        self.assertFalse(manager.pressed_keys)

    def test_worker_failure_wakes_waiter_with_error(self):
        manager_class, _, logger = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        manager.running = True
        manager.operation_queue.append({"type": "keyDown", "key": "w"})
        manager._execute_operation = Mock(side_effect=RuntimeError("input failed"))

        with patch.dict(sys.modules, {"tool.log": logger}):
            with self.assertRaisesRegex(RuntimeError, "input failed"):
                manager._worker()
            with self.assertRaisesRegex(RuntimeError, "键鼠管理器线程执行失败") as caught:
                manager.wait()

        self.assertFalse(manager.running)
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)

    def test_clean_releases_key_with_pending_keyup(self):
        manager_class, events, logger = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        manager.worker_thread = Mock()
        manager.worker_thread.is_alive.return_value = True
        with patch.dict(sys.modules, {"tool.log": logger}):
            manager._execute_operation({"type": "keyDown", "key": "w"})
            # keyUp 仍在队列中，clean() 清空队列后必须直接释放物理按键
            manager.operation_queue.append({"type": "keyUp", "key": "w"})
            manager.clean()

        self.assertEqual(events, [("down", "w"), ("up", "w")])
        self.assertFalse(manager.pressed_keys)
        self.assertFalse(manager.operation_queue)

    def test_clean_keeps_unreleased_key_for_retry(self):
        manager_class, events, logger = load_key_mouse_manager()
        manager = manager_class()
        manager.running = True
        pyautogui = manager_class.clean.__globals__["pyautogui"]
        with patch.dict(sys.modules, {"tool.log": logger}):
            manager._execute_operation({"type": "keyDown", "key": "w"})
            with patch.object(pyautogui, "keyUp", side_effect=RuntimeError("release failed")):
                manager.clean()
            self.assertEqual(manager.pressed_keys, {"w"})
            logger.CUS_LOGGER.error.assert_called_once()
            # 故障恢复后再次 clean() 可重试释放
            manager.clean()

        self.assertEqual(events, [("down", "w"), ("up", "w")])
        self.assertFalse(manager.pressed_keys)


if __name__ == "__main__":
    unittest.main()
