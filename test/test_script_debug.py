"""使用真实键鼠队列与线程验证单轮调试，仅替换桌面输入和焦点边界。"""

import unittest
from collections import deque
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.common.engine import StateKernel
from tool.key_mouse_manager import KeyMouseManager
from tool.script_tools import debug_events


class ScriptDebugTests(unittest.TestCase):
    def setUp(self):
        self.manager = KeyMouseManager()
        self.manager.set_screen_params(1920, 1080, 1920, 1080)
        self.addCleanup(self.manager.stop)
        self.enterContext(patch("core.common.engine.key_mouse_manager", self.manager))
        self.enterContext(patch("tool.script_tools.key_mouse_manager", self.manager))
        self.enterContext(patch("tool.script_tools.get_global_stop_flag", return_value=False))
        window = SimpleNamespace(hwnd=17)
        self.enterContext(patch("tool.script_tools.set_game_foreground", return_value=window))
        self.enterContext(patch("tool.script_tools.get_foreground_game_window", return_value=window))
        clock = SimpleNamespace(now=0)

        def advance(seconds):
            clock.now += seconds

        self.enterContext(patch("tool.script_tools.time", SimpleNamespace(monotonic=lambda: clock.now, sleep=advance)))
        self.cursor = self.enterContext(patch("tool.key_mouse_manager.win32api.SetCursorPos"))
        self.click = self.enterContext(patch("tool.key_mouse_manager.pyautogui.click"))
        self.key_down = self.enterContext(patch("tool.key_mouse_manager.pyautogui.keyDown"))
        self.key_up = self.enterContext(patch("tool.key_mouse_manager.pyautogui.keyUp"))
        self.kernel = StateKernel()
        self.kernel._stop = False
        self.kernel.xx, self.kernel.yy = 1920, 1080
        self.kernel.ts = Mock()
        self.kernel.get_screen = Mock()
        self.results = []
        self.finished = Event()

    def launch_debug(self, events, direct):
        def run():
            try:
                self.results.append(debug_events(self.kernel, events, direct))
            except Exception as exc:
                self.results.append(exc)
            finally:
                # 对应主窗口调试任务的 finally：操作返回后立即释放内核。
                self.manager.stop()
                self.finished.set()

        thread = Thread(target=run)
        thread.start()
        self.addCleanup(thread.join, 2)
        return thread

    def test_final_click_executes_before_cleanup_in_both_debug_modes(self):
        for direct in (True, False):
            with self.subTest(direct=direct):
                self.results.clear()
                self.finished.clear()
                self.click.reset_mock()
                self.cursor.reset_mock()
                entered, release, queued = Event(), Event(), Event()
                worker = self.manager._worker

                def delayed_worker():
                    entered.set()
                    release.wait(2)
                    worker()

                def enqueue(*args):
                    click(*args)
                    queued.set()

                click = self.manager.click
                events = [{"name": "开始挑战", "trigger": {"state_only": True},
                           "actions": [{"position": [1510, 529]}]}]
                with patch.object(self.manager, "_worker", side_effect=delayed_worker), \
                        patch.object(self.manager, "click", side_effect=enqueue):
                    thread = self.launch_debug(events, direct)
                    try:
                        self.assertTrue(entered.wait(2))
                        self.assertTrue(queued.wait(2))
                        self.assertFalse(self.finished.wait(0.05), "点击仍在队列中时不能结束调试")
                        self.click.assert_not_called()
                    finally:
                        release.set()
                        thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertIn("完成", self.results[0])
                self.click.assert_called_once_with()
                # 保留原有比例坐标换算：浮点数经整数截断后横坐标为 1511。
                self.cursor.assert_called_once_with((1511, 529))
                self.assertFalse(self.manager.running)

    def test_stop_during_press_releases_key_and_discards_following_click(self):
        for direct in (True, False):
            with self.subTest(direct=direct):
                self.kernel._stop = False
                self.results.clear()
                self.finished.clear()
                self.key_down.reset_mock()
                self.key_up.reset_mock()
                self.click.reset_mock()
                pressed = Event()
                self.key_down.side_effect = lambda _: pressed.set()
                events = [{"name": "移动", "trigger": {"state_only": True},
                           "actions": [{"press": "w", "time": 10}, {"position": [1510, 529]}]}]
                thread = self.launch_debug(events, direct)
                try:
                    self.assertTrue(pressed.wait(2))
                    self.kernel._stop = True
                    self.manager.stop()
                finally:
                    self.kernel._stop = True
                    self.manager.stop()
                    thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertIn("已停止", self.results[0])
                self.key_down.assert_called_once_with("w")
                self.key_up.assert_called_once_with("w")
                self.click.assert_not_called()

    def test_state_only_action_finishes_without_any_queued_input(self):
        thread = self.launch_debug([{"name": "切换状态", "trigger": {},
                                    "actions": [{"set_state": "ready"}]}], True)
        thread.join(2)
        try:
            self.assertFalse(thread.is_alive(), "空键鼠队列也必须允许完成调试")
            self.assertIn("1 个动作", self.results[0])
            self.assertEqual(self.kernel.state, "ready")
            self.click.assert_not_called()
            self.key_down.assert_not_called()
        finally:
            self.manager.stop()
            thread.join(2)


class KeyMouseWaitTests(unittest.TestCase):
    def setUp(self):
        self.manager = KeyMouseManager()
        self.addCleanup(self.manager.stop)

    def test_wait_returns_for_empty_queue_on_start_and_restart(self):
        for _ in range(2):
            self.manager.start()
            finished = Event()
            thread = Thread(target=lambda: (self.manager.wait(), finished.set()))
            thread.start()
            try:
                self.assertTrue(finished.wait(1))
            finally:
                self.manager.stop()
                thread.join(2)

    def test_wait_reports_worker_failure_instead_of_hanging_or_claiming_completion(self):
        with patch.object(self.manager, "_execute_operation", side_effect=RuntimeError("模拟输入失败")), \
                patch("tool.thread.get_logger", return_value=(Mock(), Mock())), \
                patch("tool.thread.get_globals", return_value=Mock()):
            self.manager.start()
            self.manager.click(10, 20)
            self.manager.worker_thread.join(2)
            self.assertFalse(self.manager.worker_thread.is_alive())
            results, finished = [], Event()

            def wait():
                try:
                    self.manager.wait()
                except RuntimeError as exc:
                    results.append(str(exc))
                finally:
                    finished.set()

            thread = Thread(target=wait)
            thread.start()
            try:
                self.assertTrue(finished.wait(1), "输入线程失败后等待必须结束")
                self.assertEqual(len(results), 1)
                self.assertIn("动作未能完成", results[0])
            finally:
                self.manager.stop()
                thread.join(2)

    def test_wait_cannot_complete_between_dequeue_and_execution(self):
        popped, release, executing, finish_action, finished = (Event() for _ in range(5))

        class PausedQueue(deque):
            def popleft(queue):
                operation = super().popleft()
                popped.set()
                release.wait(2)
                return operation

        def execute(_):
            executing.set()
            finish_action.wait(2)

        # 模拟上一项刚完成（ending=True）后取出下一项，但尚未执行的边界。
        self.manager.operation_queue = PausedQueue()
        with patch.object(self.manager, "_execute_operation", side_effect=execute):
            self.manager.start()
            self.manager.click(10, 20)
            thread = Thread(target=lambda: (self.manager.wait(), finished.set()))
            try:
                self.assertTrue(popped.wait(2))
                thread.start()
                self.assertFalse(finished.wait(0.05))
                release.set()
                self.assertTrue(executing.wait(2))
                self.assertFalse(finished.wait(0.05), "动作出队后仍未完成，不能提前返回")
                finish_action.set()
                self.assertTrue(finished.wait(2))
            finally:
                release.set()
                finish_action.set()
                if thread.ident is not None:
                    thread.join(2)
                self.manager.stop()  # 工作线程结束后才能撤销桌面输入替身。


if __name__ == "__main__":
    unittest.main()
