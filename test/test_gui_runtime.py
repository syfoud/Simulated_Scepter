"""通过完整主窗口验证运行文字下的布局，隔离热键、协议弹窗和启动清理。"""

import shutil
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QLayout, QMessageBox, QWidget

from test.core_fixture import copy_core
from tool import GLOBAL
from tool.registry import KernelRegistry
from tool.schedule import Plan
from tool.settings import load_settings, update_settings


class RuntimeGuiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # QApplication 必须先创建，主窗口导入会初始化 Qt 日志信号。
        import new_gui

        cls.module = new_gui

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        config = Path(self.folder.name)
        source = Path(self.module.PATHS["example"]) / "settings_example.json"
        (config / "settings.json").write_bytes(source.read_bytes())
        shutil.copytree(Path(self.module.PATHS["root"]) / "actions", config / "actions")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(self.module.PATHS, {"root": str(config), "config": str(config), "core": str(copy_core(config / "core")), "backup": str(config / "backup")}))
        self.stack.enter_context(patch.object(self.module.MainWindow, "setup_keyboard_listener"))
        self.stack.enter_context(patch.object(self.module.MainWindow, "check_first_launch"))
        self.stack.enter_context(patch.object(self.module, "find_game_window", return_value=Mock()))
        self.stack.enter_context(patch.object(self.module.QTimer, "singleShot"))
        # 主窗口会重绑全局日志信号；销毁后恢复原引用，避免后续测试向已释放的 Qt 窗口发信号。
        for name in ("PRINT_TO_UI", "IMAGE_TO_UI", "DIALOG"):
            self.stack.enter_context(patch.object(GLOBAL, name, None, create=True))
        self.window = self.module.MainWindow()
        self.addCleanup(self.dispose_window)

    def dispose_window(self):
        # closeEvent 会退出整个进程，因此释放窗口时不调用 close。
        self.window.hide()
        self.window.tray_icon.hide()
        GLOBAL.PRINT_TO_UI = GLOBAL.IMAGE_TO_UI = GLOBAL.DIALOG = None
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def show_window(self, width=930):
        self.window.resize(width, 760)
        self.window.show()
        self.app.processEvents()

    def set_mode(self, debug):
        update_settings({"debug": debug})
        self.window.opt = load_settings()
        self.window.update_dependent_controls_state()

    def test_filled_window_keeps_log_width_when_debug_controls_open(self):
        self.window.set_FPS(144.5)
        self.window.set_find_path_state("正在匹配交易地图，筛选目标节点并规划下一步路径")
        self.window.set_kill_num("40 / 40")
        self.window.Label_RunningState.setText("任务序列线程状态: 运行中")
        for count in range(20):
            self.window.print_to_ui(
                f"第 {count + 1} 条运行日志：已完成地图识别，正在检查交易、休整及奖励节点，继续计算下一步路径。",
                color="555555", time=True,
            )
        for width in (930, 1500):
            with self.subTest(width=width):
                self.set_mode(False)
                self.show_window(width)
                normal_width = self.window.TextBrowser.width()
                self.set_mode(True)
                self.show_window(width)
                self.assertGreaterEqual(self.window.TextBrowser.width(), normal_width)
                self.assertGreater(self.window.TextBrowser.width(), self.window.Tab1.width() * 0.65)
                self.assertGreater(self.window.engine_combo.width(), 0)
                self.assertGreater(self.window.script_combo.width(), 0)

    def test_long_status_text_and_script_name_do_not_enlarge_controls(self):
        self.set_mode(True)
        self.show_window()
        right = self.window.findChild(QLayout, "Lay_Tab1_Right")
        original = (self.window.TextBrowser.width(), right.geometry().width())
        self.window.set_find_path_state("正在搜索可用路径与目标节点" * 30)
        self.window.set_kill_num("当前击杀数及累计统计" * 30)
        self.window.script_combo.addItem("long_script_name_" * 30, "long.json")
        self.window.script_combo.setCurrentIndex(self.window.script_combo.count() - 1)
        self.show_window()
        self.assertEqual((self.window.TextBrowser.width(), right.geometry().width()), original)

    def test_engine_and_script_controls_use_separate_rows(self):
        self.set_mode(True)
        self.show_window()
        self.assertLessEqual(abs(self.window.engine_combo.geometry().center().y()
                                 - self.window.engine_settings_btn.geometry().center().y()), 1)
        self.assertLessEqual(abs(self.window.script_combo.geometry().center().y()
                                 - self.window.run_script_btn.geometry().center().y()), 1)
        self.assertGreater(self.window.script_combo.y(), self.window.engine_combo.geometry().bottom())
        self.assertGreater(self.window.engine_combo.width(), 150)
        self.assertGreater(self.window.script_combo.width(), 100)

    def test_main_window_keeps_only_general_configuration_controls(self):
        self.assertFalse(hasattr(self.window, "homeTab"))
        self.assertFalse(hasattr(self.window, "CurrencyWarTab"))
        for widget in self.window.AbyssTab.findChildren(QWidget):
            self.assertFalse(widget.objectName().startswith(("Simul_", "Diver_", "Iron_blood_", "Any_fate_", "Finger_snap_", "Currency_")))
        self.assertIsNone(self.window.findChild(QWidget, "debug_checkbox2"))

    def test_general_settings_save_preserves_configured_debug_mode(self):
        for debug in (False, True):
            self.set_mode(debug)
            with patch.object(QMessageBox, "information"):
                self.window.general_settings_save_btn.click()
            self.assertEqual(load_settings()["debug"], debug)
            self.assertIsNone(self.window.findChild(QWidget, "debug_checkbox2"))

    def test_empty_module_directory_disables_run_and_diagnostics(self):
        self.dispose_window()
        with patch.object(self.module, "KernelRegistry", return_value=KernelRegistry(Path(self.folder.name) / "missing")):
            self.window = self.module.MainWindow()
        self.assertEqual(self.window.engine_combo.count(), 0)
        self.assertFalse(self.window.kernel_rows)
        for widget in (self.window.run_script_btn, self.window.engine_settings_btn,
                       self.window.test_btn, self.window.print_btn, self.window.calibrate_btn):
            self.assertFalse(widget.isEnabled())
        self.assertFalse(self.window.restore_action.isEnabled())

    def test_gears_open_matching_configuration_in_both_modes_without_starting_tasks(self):
        dialog = Mock()
        dialog.exec_.return_value = QDialog.Rejected
        with patch.object(self.window.registry, "create_settings", return_value=dialog) as factory, \
                patch.object(self.window, "start_task") as start:
            self.set_mode(False)
            self.show_window()
            for engine, (run, button) in self.window.kernel_rows.items():
                self.assertTrue(button.isVisible())
                self.assertFalse(button.icon().isNull())
                button.click()
                factory.assert_called_with(engine, self.window)
            self.set_mode(True)
            self.assertTrue(self.window.engine_settings_btn.isVisible())
            for spec in self.window.registry.runnable():
                self.window.engine_combo.setCurrentIndex(self.window.engine_combo.findData(spec.id))
                self.window.engine_settings_btn.click()
                factory.assert_called_with(spec.id, self.window)
            start.assert_not_called()

    def test_common_selection_uses_dynamic_factory_and_survives_reopening(self):
        self.set_mode(True)
        index = self.window.engine_combo.findData("Common")
        self.assertGreaterEqual(index, 0)
        self.window.engine_combo.setCurrentIndex(index)
        self.assertEqual(load_settings()["script_engine"], "Common")
        with patch.object(self.window, "start_task", side_effect=lambda task: task()), \
                patch.object(self.window.registry, "create_engine") as factory, \
                patch.object(self.module, "run_action_script") as runner:
            self.window.run_script_btn.click()
            factory.assert_called_once_with("Common", script=True)
            runner.assert_called_once_with(factory.return_value, self.window.script_combo.currentData())
        self.dispose_window()
        self.window = self.module.MainWindow()
        self.assertEqual(self.window.engine_combo.currentData(), "Common")

    def test_debug_business_selection_runs_native_navigation_and_battle_loop(self):
        from test.test_script_runtime import script_fixture

        self.set_mode(True)
        path = Path(self.folder.name) / "selected-business.json"
        for kernel_id in ("AnyFate", "IronBlood", "FingerSnap"):
            with self.subTest(kernel_id=kernel_id):
                engine, manager, phases = script_fixture(kernel_id, path)
                self.window.engine_combo.setCurrentIndex(self.window.engine_combo.findData(kernel_id))
                self.window.refresh_scripts(str(path))
                with patch.object(self.window, "start_task", side_effect=lambda task: task()), \
                        patch.object(self.window.registry, "create_engine", return_value=engine) as factory, \
                        patch("core.common.engine.key_mouse_manager", manager), \
                        patch("tool.action_script.get_global_stop_flag", return_value=False):
                    self.window.run_script_btn.click()
                factory.assert_called_once_with(kernel_id, script=True)
                self.assertEqual(phases, ["big_world", "battle_ready"])
                self.assertEqual(engine.state, "battle")
                self.assertEqual(engine.default_json_path, str(path))
                engine.stop.assert_called_once()

    def test_manual_runs_queue_or_interrupt_plan_and_wait_for_real_thread_exit(self):
        self.window.scheduler.timer.stop()
        self.set_mode(True)
        self.window.engine_combo.setCurrentIndex(self.window.engine_combo.findData("Common"))
        path = self.window.script_combo.currentData()
        when = datetime.now().replace(microsecond=0) + timedelta(seconds=2)
        for interruptible in (False, True):
            with self.subTest(interruptible=interruptible):
                first_started, second_started, third_started = Event(), Event(), Event()
                release_first, release_second, release_third = Event(), Event(), Event()
                engines = [Mock(), Mock(), Mock()]
                calls = []

                def run_script(engine, script):
                    index = 0 if engine is engines[0] else 2
                    calls.append((index, script))
                    (first_started if index == 0 else third_started).set()
                    (release_first if index == 0 else release_third).wait()

                def run_kernel():
                    calls.append((1, None))
                    second_started.set()
                    release_second.wait()

                engines[1].start.side_effect = run_kernel
                plan = Plan.create("运行中的计划", "Common", path, when, interruptible=interruptible)
                self.window.scheduler.book.save([plan])
                with patch.object(self.window, "cleanup_at"), \
                        patch.object(self.window.registry, "create_engine", side_effect=engines) as factory, \
                        patch.object(self.module, "run_action_script", side_effect=run_script):
                    try:
                        self.window.scheduler.poll(when)
                        self.assertTrue(first_started.wait(2))
                        first_thread = self.window.task_thread
                        self.window.run_kernel("Common")
                        self.window.run_script_btn.click()
                        self.assertEqual(engines[0].stop.call_count, int(interruptible))
                        QTest.qWait(150)
                        self.assertTrue(first_thread.is_alive())
                        self.assertEqual(factory.call_count, 1)
                        self.assertFalse(second_started.is_set())
                        self.assertFalse(third_started.is_set())

                        release_first.set()
                        first_thread.join(2)
                        self.assertFalse(first_thread.is_alive())
                        self.window.scheduler.poll(when)
                        self.assertTrue(second_started.wait(2))
                        second_thread = self.window.task_thread
                        self.assertEqual(factory.call_count, 2)
                        self.assertFalse(third_started.is_set())
                        self.window.scheduler.poll(when)
                        self.assertEqual(factory.call_count, 2)

                        release_second.set()
                        second_thread.join(2)
                        self.assertFalse(second_thread.is_alive())
                        self.window.scheduler.poll(when)
                        self.assertTrue(third_started.wait(2))
                        self.assertEqual(factory.call_count, 3)
                        self.assertEqual(calls, [(0, path), (1, None), (2, path)])
                        engines[1].stop.assert_not_called()
                        engines[2].stop.assert_not_called()
                    finally:
                        release_first.set()
                        release_second.set()
                        release_third.set()
                        if self.window.task_thread is not None:
                            self.window.task_thread.join(2)
                        self.window._check_task_thread()
                        self.window.scheduler.release_active()

    def test_idle_manual_submission_cannot_overtake_an_earlier_due_plan(self):
        self.window.scheduler.timer.stop()
        when = datetime.now() - timedelta(seconds=1)
        path = self.window.script_combo.currentData()
        self.window.scheduler.book.put(Plan.create("先到期的计划", "Common", path, when))
        started, release = Event(), Event()
        engine = Mock()

        def run_script(*_):
            started.set()
            release.wait()

        with patch.object(self.window, "cleanup_at"), \
                patch.object(self.window.registry, "create_engine", return_value=engine) as factory, \
                patch.object(self.module, "run_action_script", side_effect=run_script):
            try:
                self.window.run_kernel("Common")
                self.assertTrue(started.wait(2))
                factory.assert_called_once_with("Common", script=True)
                engine.start.assert_not_called()
                thread = self.window.task_thread
                release.set()
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.window.scheduler.poll()
                self.window.task_thread.join(2)
                engine.start.assert_called_once()
                self.assertEqual(factory.call_args_list[-1].args, ("Common",))
            finally:
                release.set()
                if self.window.task_thread is not None:
                    self.window.task_thread.join(2)
                self.window._check_task_thread()

    def test_finished_interruptible_plan_cannot_interrupt_new_manual_task(self):
        self.window.scheduler.timer.stop()
        path = self.window.script_combo.currentData()
        when = datetime.now() - timedelta(seconds=1)
        self.window.scheduler.book.put(Plan.create("已结束的计划", "Common", path, when, interruptible=True))
        started, release = Event(), Event()
        engine = Mock()

        def run_kernel():
            started.set()
            release.wait()

        engine.start.side_effect = run_kernel
        with patch.object(self.window, "cleanup_at"), \
                patch.object(self.window.registry, "create_engine", return_value=engine), \
                patch.object(self.module, "run_action_script"):
            try:
                self.window.scheduler.poll()
                self.window.task_thread.join(2)
                self.assertFalse(self.window.is_task_running())
                self.window.run_kernel("Common")
                self.assertTrue(started.wait(2))
                self.window.run_script_btn.click()
                engine.stop.assert_not_called()
                self.assertTrue(self.window.is_task_running())
            finally:
                release.set()
                if self.window.task_thread is not None:
                    self.window.task_thread.join(2)
                self.window.scheduler.pending.clear()
                self.window._check_task_thread()

    def test_editor_debug_finishes_click_before_releasing_engine_and_reporting_result(self):
        from types import SimpleNamespace

        from core.common.engine import StateKernel
        from tool.key_mouse_manager import KeyMouseManager

        self.window.scheduler.timer.stop()
        collector = Mock()
        self.window.script_tool_result.connect(collector)
        for direct in (True, False):
            with self.subTest(direct=direct):
                collector.reset_mock()
                manager = KeyMouseManager()
                manager.set_screen_params(1920, 1080, 1920, 1080)
                engine = StateKernel()
                engine._stop = False
                engine.xx, engine.yy = 1920, 1080
                engine.ts, engine.get_screen = Mock(), Mock()
                clicked, release = Event(), Event()

                def click():
                    clicked.set()
                    release.wait(2)

                def stop():
                    engine._stop = True
                    manager.stop()

                engine.stop = Mock(side_effect=stop)
                focus = SimpleNamespace(hwnd=17)
                events = [{"name": "开始挑战", "trigger": {"state_only": True},
                           "actions": [{"position": [1510, 529]}]}]
                with patch.object(self.window, "cleanup_at"), \
                        patch.object(self.window.registry, "create_engine", return_value=engine), \
                        patch("core.common.engine.key_mouse_manager", manager), \
                        patch("tool.script_tools.key_mouse_manager", manager), \
                        patch("tool.script_tools.set_game_foreground", return_value=focus), \
                        patch("tool.script_tools.get_foreground_game_window", return_value=focus), \
                        patch("tool.key_mouse_manager.pyautogui.click", side_effect=click), \
                        patch("tool.key_mouse_manager.win32api.SetCursorPos") as cursor:
                    try:
                        self.window.debug_script_events("debug-click", "Common", events, direct)
                        self.assertTrue(clicked.wait(2))
                        self.app.processEvents()
                        self.assertTrue(self.window.is_task_running())
                        engine.stop.assert_not_called()
                        collector.assert_not_called()
                        release.set()
                        self.window.task_thread.join(2)
                        self.assertFalse(self.window.is_task_running())
                        self.app.processEvents()
                        self.assertIn("完成", collector.call_args.args[1]["message"])
                        engine.stop.assert_called_once()
                        cursor.assert_called_once_with((1511, 529))
                    finally:
                        release.set()
                        if self.window.task_thread is not None:
                            self.window.task_thread.join(2)
                        manager.stop()
                        self.window._check_task_thread()

    def test_editor_sample_reports_result_or_error_and_releases_engine(self):
        self.window.scheduler.timer.stop()
        collector = Mock()
        self.window.script_tool_result.connect(collector)
        for failure in (False, True):
            with self.subTest(failure=failure):
                engine = Mock(_stop=False)
                sample = {"screen": "frozen frame", "texts": []}
                session = f"sample-{failure}"
                with patch.object(self.window, "cleanup_at"), \
                        patch.object(self.window.registry, "create_engine", return_value=engine) as factory, \
                        patch.object(self.module, "capture_sample", return_value=sample,
                                     side_effect=OSError("截图失败") if failure else None):
                    self.window.capture_script_sample(session, "Common", False)
                    self.window.task_thread.join(2)
                    self.assertFalse(self.window.is_task_running())
                    self.app.processEvents()
                    factory.assert_called_once_with("Common", script=True)
                    engine.stop.assert_called_once()
                    self.assertNotIn(session, self.window.editor_tasks)
                    result = collector.call_args.args[1]
                    if failure:
                        self.assertIn("截图失败", result["error"])
                    else:
                        self.assertIs(result["sample"], sample)
                    self.window._check_task_thread()

    def test_editor_reports_missing_game_without_waiting_for_kernel_initialization(self):
        collector = Mock()
        self.window.script_tool_result.connect(collector)
        with patch.object(self.window, "cleanup_at"), \
                patch.object(self.module, "find_game_window", return_value=None), \
                patch.object(self.window.registry, "create_engine") as factory:
            self.window.capture_script_sample("no-game", "Common", True)
            self.window.task_thread.join(2)
            self.assertFalse(self.window.is_task_running())
            self.app.processEvents()
            self.assertIn("未找到游戏窗口", collector.call_args.args[1]["error"])
            factory.assert_not_called()
            self.window._check_task_thread()

    def test_cancelled_sample_wait_is_reported_as_stopped_and_releases_engine(self):
        collector = Mock()
        self.window.script_tool_result.connect(collector)
        engine = Mock(_stop=False)
        with patch.object(self.window, "cleanup_at"), \
                patch.object(self.window.registry, "create_engine", return_value=engine), \
                patch.object(self.module, "capture_sample", side_effect=InterruptedError("截图已停止")):
            self.window.capture_script_sample("waiting-focus", "Common", False)
            self.window.task_thread.join(2)
            self.assertFalse(self.window.is_task_running())
            self.app.processEvents()
            self.assertEqual(collector.call_args.args, ("waiting-focus", {"message": "操作已停止"}))
            engine.stop.assert_called_once()
            self.window._check_task_thread()

    def test_cancelling_queued_editor_debug_preserves_current_task(self):
        self.window.scheduler.timer.stop()
        entered, release = Event(), Event()
        engine = Mock(_stop=False)
        collector = Mock()
        self.window.script_tool_result.connect(collector)

        def run_kernel():
            entered.set()
            release.wait()

        engine.start.side_effect = run_kernel
        with patch.object(self.window, "cleanup_at"), \
                patch.object(self.window.registry, "create_engine", return_value=engine) as factory:
            try:
                self.window.run_kernel("Common")
                self.assertTrue(entered.wait(2))
                self.window.debug_script_events("queued-debug", "Common", [], True)
                self.assertEqual(factory.call_count, 1)
                self.window.stop_editor_task("queued-debug")
                self.assertFalse(self.window.scheduler.pending)
                self.assertTrue(self.window.is_task_running())
                engine.stop.assert_not_called()
                self.assertEqual(collector.call_args.args, ("queued-debug", {"message": "排队任务已取消"}))
                self.assertNotIn("queued-debug", self.window.editor_tasks)
            finally:
                release.set()
                self.window.task_thread.join(2)
                self.window._check_task_thread()

    def test_stopping_editor_debug_waits_for_real_thread_before_next_task(self):
        self.window.scheduler.timer.stop()
        entered, release = Event(), Event()
        engine = Mock(_stop=False)
        engine.stop.side_effect = lambda: setattr(engine, "_stop", True)
        collector, next_task = Mock(), Mock()
        self.window.script_tool_result.connect(collector)

        def debug(*_):
            entered.set()
            release.wait()
            return "完成"

        with patch.object(self.window, "cleanup_at"), \
                patch.object(self.window.registry, "create_engine", return_value=engine), \
                patch.object(self.module, "debug_events", side_effect=debug):
            try:
                self.window.debug_script_events("active-debug", "Common", [], True)
                self.assertTrue(entered.wait(2))
                self.window.start_task(next_task)
                self.window.stop_editor_task("active-debug")
                engine.stop.assert_called_once()
                QTest.qWait(150)
                self.assertTrue(self.window.is_task_running())
                next_task.assert_not_called()
                thread = self.window.task_thread
                release.set()
                thread.join(2)
                self.app.processEvents()
                self.assertEqual(collector.call_args.args, ("active-debug", {"message": "操作已停止"}))
                self.window.scheduler.poll()
                self.window.task_thread.join(2)
                next_task.assert_called_once()
            finally:
                release.set()
                if self.window.task_thread is not None:
                    self.window.task_thread.join(2)
                self.window._check_task_thread()


if __name__ == "__main__":
    unittest.main()
