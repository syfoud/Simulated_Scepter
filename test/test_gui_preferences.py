"""使用真实 Qt 控件验证界面模式与自由脚本选项持久化，隔离游戏和键鼠操作。"""

import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import uic
from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSlot
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from route import PATHS
from test.core_fixture import copy_core
from test.test_task_completion import load_task
from tool.registry import KernelRegistry
from tool.script_files import discover_scripts, read_script, script_key, script_path
from tool.settings import load_settings, update_settings

ROOT = Path(__file__).resolve().parents[1]


class GuiPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_id = QFontDatabase.addApplicationFont(str(ROOT / "resource/font/ChironGoRoundTC-350N.ttf"))
        cls.app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 8))

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.actions = self.root / "actions"
        self.actions.mkdir()
        self.config = self.root / "config"
        self.config.mkdir()
        self.settings = self.config / "settings.json"
        self.settings.write_text(json.dumps({
            "debug": False, "hotkeys": {"stop": "f8"}, "other": {"keep": True},
        }), encoding="utf-8")
        for name in ("a.json", "中文脚本.json"):
            (self.actions / name).write_text('[{"name": "确认", "trigger": {"state_only": true}, "actions": [{"sleep": 1}]}]', encoding="utf-8")
        self.core = copy_core(self.root / "core")
        # 本组测试只用用户脚本；模块自带脚本在注册表和原生主窗口测试中覆盖。
        for script in self.core.glob("*/actions/*.json"):
            script.unlink()
        self.logger = Mock()
        self.dialogs = Mock()
        self.script_runner = Mock()
        self.enterContext(patch.dict(PATHS, {"root": str(self.root), "config": str(self.config), "example": str(self.root / "example"), "core": str(self.core), "backup": str(self.root / "backup")}))
        self.gui = self.make_gui()

    def make_gui(self):
        window = uic.loadUi(str(ROOT / "resource/ui/UI.ui"), QMainWindow())
        self.addCleanup(window.close)
        gui = load_task("new_gui.py", "MainWindow", {
            "init_kernel_buttons", "init_script_controls", "save_script_selection", "refresh_scripts", "run_script", "launch_script",
            "update_settings", "update_dependent_controls_state",
            "connect_dependency_signals", "handle_key_pressed",
        }, {
            "os": os, "json": json, "shutil": shutil, "pyqtSlot": pyqtSlot,
            "time": SimpleNamespace(localtime=lambda: SimpleNamespace(tm_hour=12)),
            "Qt": Qt, "QSignalBlocker": QSignalBlocker, "QWidget": QWidget, "QHBoxLayout": QHBoxLayout,
            "QPushButton": QPushButton, "QSizePolicy": QSizePolicy, "QToolButton": QToolButton,
            "CUS_LOGGER": self.logger, "QMessageBox": self.dialogs,
            "run_action_script": self.script_runner,
            "discover_scripts": discover_scripts, "read_script": read_script,
            "script_key": script_key, "script_path": script_path,
            "update_settings": update_settings,
            "EXTRA": SimpleNamespace(FILE_LOCK=threading.Lock()),
            "PATHS": {"root": str(self.root), "config": str(self.config),
                      "example": str(self.root / "example"), "core": str(self.core), "backup": str(self.root / "backup")},
        })
        for widget in window.findChildren(QWidget) + window.findChildren(QLayout):
            if widget.objectName():
                setattr(gui, widget.objectName(), widget)
        gui.registry = KernelRegistry()
        gui.registry.create_engine = Mock(return_value=Mock())
        gui.set_exit_and_minimized_btn_icon = Mock()
        gui.init_kernel_buttons()
        gui.opt = json.loads(self.settings.read_text(encoding="utf-8"))
        gui.start_task = Mock()
        gui.load_hotkey_config = Mock(return_value={"stop": "f8"})
        gui.is_task_running = Mock(return_value=False)
        gui.show_task_running_warning = Mock()
        return gui

    def set_mode(self, debug):
        update_settings({"debug": debug})
        self.gui.opt = load_settings()
        self.gui.update_dependent_controls_state()

    def test_mode_switches_controls_in_both_directions(self):
        self.gui.connect_dependency_signals()
        for debug in (False, True, False):
            with self.subTest(debug=debug):
                self.set_mode(debug)
                self.assertEqual(self.gui.kernel_buttons.isHidden(), debug)
                for name in ("engine_label", "engine_combo", "engine_settings_btn",
                             "script_label", "script_combo", "run_script_btn",
                             "test_btn", "print_btn", "PrintEdit", "PrintPhoto",
                             "PrintText", "label_test_hotkey", "test_hotkey_input",
                             "label_print_hotkey", "print_hotkey_input", "debug_group"):
                    self.assertEqual(getattr(self.gui, name).isHidden(), not debug, name)
                for name in ("stop_btn", "label_stop_hotkey", "stop_hotkey_input",
                             "hotkey_save_btn", "calibrate_btn"):
                    self.assertFalse(getattr(self.gui, name).isHidden(), name)

    def test_other_settings_keep_mode_visibility_and_recording_dependencies(self):
        self.gui.connect_dependency_signals()
        for debug in (False, True):
            self.set_mode(debug)
            self.gui.recording_checkBox2.setChecked(True)
            self.assertEqual(self.gui.test_btn.isHidden(), not debug)
            self.assertEqual(self.gui.kernel_buttons.isHidden(), debug)
            self.assertTrue(self.gui.recording_time_input.isEnabled())
            self.assertEqual(self.gui.recording_label_checkbox.isEnabled(), debug)
            self.gui.recording_checkBox2.setChecked(False)
            self.assertFalse(self.gui.recording_time_input.isEnabled())
            self.assertFalse(self.gui.recording_label_checkbox.isEnabled())

    def test_long_script_names_leave_most_width_for_logs(self):
        self.gui.init_script_controls()
        self.gui.script_combo.addItem("script_" * 30, str(self.actions / "long.json"))
        self.gui.script_combo.setCurrentIndex(self.gui.script_combo.count() - 1)
        window = self.gui.TextBrowser.window()
        for debug in (True, False):
            self.set_mode(debug)
            for width in (930, 1500):
                with self.subTest(debug=debug, width=width):
                    window.resize(width, 760)
                    window.show()
                    self.app.processEvents()
                    self.assertGreater(self.gui.TextBrowser.width(), window.Tab1.width() * 0.6)
                    self.assertGreater(self.gui.TextBrowser.width(), self.gui.engine_combo.width())

    def test_buttons_stay_close_to_separator_when_window_grows(self):
        self.gui.init_script_controls()
        window = self.gui.TextBrowser.window()
        separator = window.findChild(QWidget, "line_99")
        for debug in (False, True):
            self.set_mode(debug)
            for height in (760, 1000):
                with self.subTest(debug=debug, height=height):
                    window.resize(930, height)
                    window.show()
                    self.app.processEvents()
                    first = self.gui.engine_combo if debug else self.gui.kernel_buttons
                    gap = first.y() - separator.geometry().bottom() - 1
                    self.assertGreaterEqual(gap, 0)
                    self.assertLessEqual(gap, 12)

    def test_finger_snap_button_is_removed_and_kernel_runs_selected_script(self):
        self.assertIsNone(self.gui.engine_combo.window().findChild(QWidget, "finger_snap_btn"))
        self.gui.init_script_controls()
        self.gui.engine_combo.setCurrentText("FingerSnap")
        engine_class = self.gui.engine_combo.currentData()
        self.assertEqual(engine_class, "FingerSnap")
        self.gui.run_script_btn.click()
        # 点击运行后切换下拉框，已启动任务仍使用点击时的弹指内核和脚本。
        self.gui.engine_combo.setCurrentText("Currency")
        self.gui.script_combo.setCurrentText("中文脚本")
        worker = self.gui.start_task.call_args.args[0]
        worker()
        self.gui.registry.create_engine.assert_called_once_with("FingerSnap", script=True)
        self.assertIs(self.gui.current_task, self.gui.registry.create_engine.return_value)
        self.script_runner.assert_called_once_with(self.gui.current_task, str(self.actions / "a.json"))
        self.gui.engine_combo.setCurrentText("FingerSnap")
        reopened = self.make_gui()
        reopened.init_script_controls()
        self.assertEqual(reopened.engine_combo.currentText(), "FingerSnap")
        self.assertEqual(reopened.script_combo.currentText(), "中文脚本")

    def test_normal_mode_ignores_debug_hotkeys_but_allows_stop(self):
        callbacks = {name: Mock() for name in ("test", "print", "stop")}
        self.gui.test_btn.clicked.connect(callbacks["test"])
        self.gui.print_btn.clicked.connect(callbacks["print"])
        self.gui.stop_btn.clicked.connect(callbacks["stop"])
        for running in (False, True):
            self.gui.is_task_running.return_value = running
            for action in ("test", "print", "stop"):
                self.gui.handle_key_pressed(action)
        callbacks["test"].assert_not_called()
        callbacks["print"].assert_not_called()
        callbacks["stop"].assert_called_once()
        self.gui.show_task_running_warning.assert_not_called()

    def test_debug_hotkeys_run_when_idle_and_warn_during_task(self):
        self.set_mode(True)
        callbacks = {name: Mock() for name in ("test", "print", "stop")}
        self.gui.test_btn.clicked.connect(callbacks["test"])
        self.gui.print_btn.clicked.connect(callbacks["print"])
        self.gui.stop_btn.clicked.connect(callbacks["stop"])
        for running in (False, True):
            self.gui.is_task_running.return_value = running
            for action in ("test", "print", "stop"):
                self.gui.handle_key_pressed(action)
        for callback in callbacks.values():
            callback.assert_called_once()
        self.assertEqual(self.gui.show_task_running_warning.call_count, 2)

    def test_dropdown_changes_survive_reopening_without_losing_other_settings(self):
        self.gui.init_script_controls()
        self.gui.engine_combo.setCurrentText("Currency")
        self.gui.script_combo.setCurrentText("中文脚本")
        saved = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(saved["script_engine"], "Currency")
        self.assertEqual(saved["script_file"], "actions/中文脚本.json")
        self.assertEqual(saved["other"], {"keep": True})
        self.assertEqual(saved["hotkeys"], {"stop": "f8"})
        reopened = self.make_gui()
        reopened.init_script_controls()
        self.assertEqual(reopened.engine_combo.currentText(), "Currency")
        self.assertEqual(reopened.script_combo.currentData(), str(self.actions / "中文脚本.json"))
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), saved)

    def test_restoration_and_legacy_defaults_do_not_write_during_startup(self):
        for selection in ({}, {"script_engine": "IronBlood", "script_file": "中文脚本.json"}):
            with self.subTest(selection=selection):
                self.gui = self.make_gui()
                self.gui.opt.update(selection)
                original = self.settings.read_bytes()
                self.gui.init_script_controls()
                self.assertEqual(self.gui.engine_combo.currentText(), selection.get("script_engine", "Simulated"))
                self.assertEqual(Path(self.gui.script_combo.currentData()).name, selection.get("script_file", "a.json"))
                self.assertEqual(self.settings.read_bytes(), original)

    def test_unavailable_saved_options_fall_back_to_first_available_items(self):
        self.gui.opt.update({"script_engine": "RemovedEngine", "script_file": "missing.json"})
        self.gui.init_script_controls()
        self.assertEqual(self.gui.engine_combo.currentText(), "Simulated")
        self.assertEqual(self.gui.script_combo.currentText(), "a")
        self.assertTrue(self.gui.run_script_btn.isEnabled())

    def test_empty_script_list_disables_run_and_keeps_saved_filename(self):
        for path in self.actions.iterdir():
            path.unlink()
        saved = {"script_engine": "IronBlood", "script_file": "中文脚本.json"}
        self.settings.write_text(json.dumps(saved), encoding="utf-8")
        self.gui = self.make_gui()
        self.gui.init_script_controls()
        self.assertFalse(self.gui.run_script_btn.isEnabled())
        self.assertFalse(self.gui.script_combo.isEnabled())
        self.gui.engine_combo.setCurrentText("Currency")
        saved["script_engine"] = "Currency"
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), saved)

    def test_save_failure_reports_error_without_claiming_success(self):
        self.gui.init_script_controls()
        original = self.settings.read_bytes()
        self.gui.update_settings = Mock(side_effect=OSError("无法写入"))
        self.gui.engine_combo.setCurrentText("Currency")
        self.logger.error.assert_called_once()
        self.dialogs.warning.assert_called_once()
        self.assertEqual(self.settings.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
