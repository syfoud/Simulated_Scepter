"""键位自定义相关测试：录键交互、读取期校验、键位冲突提示与键名转换。

改程序热键的默认键 / 录入范围时，本文件与以下位置需要同步修改：
- 默认热键值：resource/gui_settings_default.json 的 hotkeys、new_gui.py 里 load_hotkey_config 的 default_config
- 热键可录制范围：tool/gui/game_key_dialog.py 的 _event_key_name / _qt_key_to_virtual_key / _EXTENDED_KEY_NAMES
- 热键名转 keyboard 库写法：new_gui.py 的 _KEYBOARD_KEY_NAMES
"""

import os
import types
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QFocusEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLineEdit

from tool.gui.game_key_dialog import (
    GAME_KEY_LABELS,
    GAME_KEY_ROWS,
    GameKeyDialog,
    KeyCapture,
    display_key_name,
)
from tool.key_mouse_manager import is_valid_key_name


class KeyCaptureTests(unittest.TestCase):
    """录键框：点一次录一个键，取消/失焦还原，Delete 与校验的行为。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_capture(self, value="", allow_empty=False, validator=None, allow_tab=False):
        edit = QLineEdit()
        self.addCleanup(edit.deleteLater)
        capture = KeyCapture(edit, allow_empty=allow_empty, validator=validator,
                             allow_tab=allow_tab)
        capture.set_key_name(value)
        return edit, capture

    def test_begin_capture_clears_box_and_shows_placeholder(self):
        edit, capture = self.make_capture("f5")

        capture.begin_capture()

        self.assertTrue(capture.is_capturing())
        self.assertEqual(edit.text(), "")
        self.assertEqual(edit.placeholderText(), "请按下新按键")

    def test_first_key_is_recorded_and_capture_ends(self):
        edit, capture = self.make_capture("f5")

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_T)

        self.assertEqual(capture.key_name, "t")
        self.assertEqual(edit.text(), "T")
        self.assertFalse(capture.is_capturing())

    def test_later_keys_do_not_overwrite_recorded_key(self):
        edit, capture = self.make_capture("f5")

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_T)
        QTest.keyClick(edit, Qt.Key_Y)

        self.assertEqual(capture.key_name, "t")
        self.assertEqual(edit.text(), "T")

    def test_cancel_restores_previous_value(self):
        edit, capture = self.make_capture("f5")

        capture.begin_capture()
        capture.cancel_capture()

        self.assertFalse(capture.is_capturing())
        self.assertEqual(capture.key_name, "f5")
        self.assertEqual(edit.text(), "F5")

    def test_escape_cancels_and_restores(self):
        edit, capture = self.make_capture("f5")

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_Escape)

        self.assertFalse(capture.is_capturing())
        self.assertEqual(capture.key_name, "f5")

    def test_focus_out_cancels_and_restores(self):
        edit, capture = self.make_capture("f5")

        capture.begin_capture()
        QApplication.sendEvent(edit, QFocusEvent(QEvent.FocusOut))

        self.assertFalse(capture.is_capturing())
        self.assertEqual(capture.key_name, "f5")
        self.assertEqual(edit.text(), "F5")

    def test_delete_clears_hotkey_when_empty_allowed(self):
        edit, capture = self.make_capture("f5", allow_empty=True)

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_Delete)

        self.assertEqual(capture.key_name, "")
        self.assertEqual(edit.text(), "")
        self.assertEqual(edit.placeholderText(), "未设置")

    def test_game_key_capture_rejects_unavailable_key(self):
        edit, capture = self.make_capture("f", validator=is_valid_key_name)

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_End)

        # 不提交、保持等待，并说明原因
        self.assertTrue(capture.is_capturing())
        self.assertEqual(capture.key_name, "f")
        self.assertEqual(edit.placeholderText(), "该按键不可用，请重新按下")
        self.assertEqual(edit.text(), "")

    def test_game_key_capture_accepts_legal_key_after_rejection(self):
        edit, capture = self.make_capture("f", validator=is_valid_key_name)

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_End)
        QTest.keyClick(edit, Qt.Key_T)

        self.assertEqual(capture.key_name, "t")
        self.assertFalse(capture.is_capturing())

    def test_unrecognized_key_warns_and_keeps_waiting(self):
        # 符号键这类既没有键名、游戏也用不了的键，也要给出提示而不是静默等待
        edit, capture = self.make_capture("f", validator=is_valid_key_name)

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_Minus)

        self.assertTrue(capture.is_capturing())
        self.assertEqual(capture.key_name, "f")
        self.assertEqual(edit.placeholderText(), "该按键不可用，请重新按下")

    def test_program_hotkey_can_record_tab(self):
        # 程序热键允许 Tab（全局监听不受焦点影响）；游戏键位没有 Tab 这一项
        edit, capture = self.make_capture("end", allow_empty=True, allow_tab=True)

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_Tab)

        self.assertFalse(capture.is_capturing())
        self.assertEqual(capture.key_name, "tab")
        self.assertEqual(edit.text(), "Tab")

    def test_game_key_capture_tab_cancels_and_keeps_previous_key(self):
        edit, capture = self.make_capture("f", validator=is_valid_key_name)

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_Tab)

        self.assertFalse(capture.is_capturing())
        self.assertEqual(capture.key_name, "f")

    def test_capture_state_signal_is_paired(self):
        edit, capture = self.make_capture("f5")
        states = []
        capture.capture_state_changed.connect(states.append)

        capture.begin_capture()
        QTest.keyClick(edit, Qt.Key_T)

        self.assertEqual(states, [True, False])


class KeyNameDisplayTests(unittest.TestCase):
    """键名展示：录制值与界面文案的对应关系。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_display_names(self):
        expected = {
            "space": "空格",
            "enter": "Enter",
            "end": "End",
            "pause": "Pause",
            "pageup": "PageUp",
            "pagedown": "PageDown",
            "home": "Home",
            "insert": "Insert",
            "delete": "Delete",
            "printscreen": "PrintScreen",
            "numlock": "NumLock",
            "scrolllock": "ScrollLock",
            "up": "↑",
            "down": "↓",
            "left": "←",
            "right": "→",
            "shiftleft": "LeftShift",
            "shiftright": "RightShift",
            "ctrlleft": "Ctrl",
            "altright": "RightAlt",
            "tab": "Tab",
        }
        for name, text in expected.items():
            with self.subTest(name=name):
                self.assertEqual(display_key_name(name), text)

    def test_unknown_key_falls_back_to_upper(self):
        self.assertEqual(display_key_name("f5"), "F5")


class HotkeyNameConversionTests(unittest.TestCase):
    """热键下发前的键名转换：转 keyboard 库写法与可注册性判断。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        import new_gui

        cls.module = new_gui

    def test_modifier_names_are_side_specific(self):
        expected = {
            "shiftleft": "left shift",
            "shiftright": "right shift",
            "ctrlleft": "left ctrl",
            "ctrlright": "right ctrl",
            "altleft": "left alt",
            "altright": "right alt",
        }
        for name, keyboard_name in expected.items():
            with self.subTest(name=name):
                self.assertEqual(self.module.to_keyboard_key_name(name), keyboard_name)

    def test_extended_key_names(self):
        expected = {
            "pageup": "page up",
            "pagedown": "page down",
            "capslock": "caps lock",
            "numlock": "num lock",
            "scrolllock": "scroll lock",
            "printscreen": "print screen",
        }
        for name, keyboard_name in expected.items():
            with self.subTest(name=name):
                self.assertEqual(self.module.to_keyboard_key_name(name), keyboard_name)

    def test_plain_keys_keep_name(self):
        self.assertEqual(self.module.to_keyboard_key_name("f5"), "f5")
        self.assertEqual(self.module.to_keyboard_key_name("end"), "end")
        self.assertEqual(self.module.to_keyboard_key_name("a"), "a")

    def test_empty_and_none_mean_unbound(self):
        self.assertEqual(self.module.to_keyboard_key_name(""), "")
        self.assertEqual(self.module.to_keyboard_key_name(None), "")
        self.assertEqual(self.module.to_keyboard_key_name("none"), "")

    def test_insert_keyboard_lib_spelling_is_normalized(self):
        self.assertEqual(self.module.to_keyboard_key_name("left shift"), "left shift")

    def test_registerable_hotkey(self):
        self.assertTrue(self.module.is_registerable_hotkey("f5"))
        self.assertTrue(self.module.is_registerable_hotkey("end"))
        self.assertTrue(self.module.is_registerable_hotkey("tab"))
        self.assertTrue(self.module.is_registerable_hotkey("left shift"))
        self.assertFalse(self.module.is_registerable_hotkey(""))
        self.assertFalse(self.module.is_registerable_hotkey("none"))
        self.assertFalse(self.module.is_registerable_hotkey("badkey"))


class HotkeyConfigLoadTests(unittest.TestCase):
    """读取期校验：非法热键回退默认、空值表示不使用。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        import new_gui

        cls.module = new_gui

    def load(self, hotkeys):
        with patch.object(self.module, "load_settings", return_value={"hotkeys": hotkeys}):
            return self.module.MainWindow.load_hotkey_config(types.SimpleNamespace())

    def test_missing_keys_fall_back_to_defaults(self):
        self.assertEqual(
            self.load({}),
            {"stop": "end", "test": "f6", "print": "f7"},
        )

    def test_non_dict_hotkeys_fall_back_to_defaults(self):
        self.assertEqual(
            self.load("f5"),
            {"stop": "end", "test": "f6", "print": "f7"},
        )

    def test_invalid_key_warns_and_falls_back_to_default(self):
        with patch.object(self.module.CUS_LOGGER, "warning") as warning:
            result = self.load({"stop": "badkey", "test": "f6", "print": "f7"})

        self.assertEqual(result["stop"], "end")
        self.assertEqual(warning.call_count, 1)

    def test_empty_and_none_mean_unbound(self):
        result = self.load({"stop": "", "test": "none", "print": "f7"})

        self.assertEqual(result, {"stop": "", "test": "", "print": "f7"})

    def test_keyboard_lib_spelling_is_normalized(self):
        result = self.load({"stop": "left shift", "test": "f6", "print": "f7"})

        self.assertEqual(result["stop"], "shiftleft")


class KeyWarningTests(unittest.TestCase):
    """保存前的重复/冲突提示文案。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        import new_gui

        cls.module = new_gui

    def message(self, game_keys, hotkeys=None, debug=False):
        return self.module.MainWindow._build_key_warning_message(
            game_keys, GAME_KEY_LABELS, hotkeys, debug)

    def test_default_duplicate_is_reported(self):
        message = self.message({"tutorial": "g", "tutorial_hints": "g", "interact": "f"})

        self.assertIn("教学目录", message)
        self.assertIn("新手提示", message)
        self.assertIn("重复", message)

    def test_game_key_conflicts_with_stop_hotkey(self):
        message = self.message({"shop": "f5"}, {"stop": "f5", "test": "f6", "print": "f7"})

        self.assertIn("商店", message)
        self.assertIn("停止任务", message)
        self.assertNotIn("截图测试", message)
        self.assertNotIn("打印坐标", message)

    def test_test_hotkey_conflict_only_reported_in_debug(self):
        game_keys = {"interact": "f6", "shop": "f5"}
        hotkeys = {"stop": "end", "test": "f6", "print": "f7"}

        self.assertEqual(self.message(game_keys, hotkeys, False), "")
        self.assertIn("截图测试", self.message(game_keys, hotkeys, True))

    def test_no_duplicate_and_no_conflict(self):
        message = self.message(
            {"interact": "f", "shop": "f5", "move_w": "w"},
            {"stop": "end", "test": "f6", "print": "f7"},
        )

        self.assertEqual(message, "")

    def test_unbound_hotkey_is_skipped(self):
        message = self.message({"interact": "f"}, {"stop": "", "test": "", "print": ""})

        self.assertEqual(message, "")


class GameKeyDialogTests(unittest.TestCase):
    """游戏内键位窗口：行数、固定行、恢复默认与取值。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    DEFAULTS = {
        "character": "c",
        "interact": "f",
        "shop": "f5",
        "role_1": "1",
        "move_w": "w",
        "sprint": "shiftleft",
    }

    def make_dialog(self, current=None):
        defaults = {"game_keys": dict(self.DEFAULTS)}
        saved = {"game_keys": dict(current if current is not None else self.DEFAULTS)}
        stack = (
            patch("tool.settings.load_default_settings", return_value=defaults),
            patch("tool.settings.load_settings", return_value=saved),
        )
        for patcher in stack:
            self.addCleanup(patcher.stop)
            patcher.start()
        dialog = GameKeyDialog(None)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_all_game_rows_present_and_fixed_rows_read_only(self):
        dialog = self.make_dialog()

        editable = [name for _label, name, _fixed in GAME_KEY_ROWS if name]
        self.assertEqual(len(dialog._captures), len(editable))
        self.assertEqual(len(editable) + 2, len(GAME_KEY_ROWS))
        self.assertEqual(dialog.game_keys(), {
            name: self.DEFAULTS.get(name, "") for name in editable})

    def test_restore_defaults_only_changes_window_values(self):
        dialog = self.make_dialog(current={**self.DEFAULTS, "character": "t"})
        self.assertEqual(dialog.game_keys()["character"], "t")

        dialog.restore_defaults()

        self.assertEqual(dialog.game_keys()["character"], "c")


class SaveHotkeyConfigTests(unittest.TestCase):
    """保存链路：录键值写入、整表写入 game_keys、运行中拒存与写盘失败。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        import new_gui

        cls.module = new_gui

    DEFAULTS = {
        "character": "c",
        "interact": "f",
        "shop": "f5",
        "move_w": "w",
        "sprint": "shiftleft",
    }

    class MessageRecorder:
        calls = []

        @classmethod
        def warning(cls, parent, title, text):
            cls.calls.append(("warning", title, text))

        @classmethod
        def information(cls, parent, title, text):
            cls.calls.append(("information", title, text))

    def make_window(self, captures, pending=None, opt=None, running=False, fail=None):
        window = types.SimpleNamespace()
        window.is_task_running = Mock(return_value=running)
        window._hotkey_captures = {
            action: types.SimpleNamespace(key_name=key_name)
            for action, key_name in captures.items()
        }
        window.hotkey_config = {"stop": "end", "test": "f6", "print": "f7"}
        window.pending_game_keys = pending
        window.opt = opt or {"debug": False, "game_keys": dict(self.DEFAULTS)}
        window.saved = {}

        def update_settings(config):
            if fail is not None:
                raise OSError(fail)
            window.saved.update(config)

        window.update_settings = update_settings
        window.refresh_keyboard_listener = Mock()
        window.update_button_hotkey_text = Mock()
        window.save_hotkey_config = self.module.MainWindow.save_hotkey_config.__get__(window)
        window._build_key_warning_message = self.module.MainWindow._build_key_warning_message
        return window

    def setUp(self):
        # 用类本身作为 QMessageBox 替身：弹出记录是类属性，不实例化
        self.recorder = self.MessageRecorder
        self.recorder.calls = []
        patchers = (
            patch.object(self.module, "QMessageBox", self.recorder),
            patch.object(self.module, "load_default_settings",
                         return_value={"game_keys": dict(self.DEFAULTS)}),
            patch("tool.key_mouse_manager.reload_game_keys"),
        )
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_save_uses_recorded_hotkeys_and_whole_game_keys(self):
        window = self.make_window({"stop": "end", "test": "", "print": "f7"})

        window.save_hotkey_config()

        self.assertEqual(window.saved["hotkeys"], {"stop": "end", "test": "", "print": "f7"})
        self.assertEqual(window.saved["game_keys"], self.DEFAULTS)
        self.assertIsNone(window.pending_game_keys)
        window.refresh_keyboard_listener.assert_called_once()
        window.update_button_hotkey_text.assert_called_once_with(
            {"stop": "end", "test": "", "print": "f7"})
        self.assertEqual(self.recorder.calls[-1], ("information", "提示", "快捷键配置已保存"))

    def test_save_reports_game_key_hotkey_conflict(self):
        window = self.make_window(
            {"stop": "f5", "test": "f6", "print": "f7"},
            opt={"debug": False, "game_keys": dict(self.DEFAULTS)})

        window.save_hotkey_config()

        kind, _title, text = self.recorder.calls[-1]
        self.assertEqual(kind, "warning")
        self.assertIn("商店", text)
        self.assertIn("停止任务", text)
        self.assertEqual(window.saved["hotkeys"]["stop"], "f5")

    def test_save_is_refused_while_task_running(self):
        window = self.make_window({"stop": "end"}, running=True)

        window.save_hotkey_config()

        self.assertEqual(window.saved, {})
        kind, _title, text = self.recorder.calls[-1]
        self.assertEqual(kind, "warning")
        self.assertIn("任务运行中", text)
        self.assertIn("无法保存", text)

    def test_write_failure_is_reported_without_false_success(self):
        window = self.make_window({"stop": "end"}, fail="无法写入")

        window.save_hotkey_config()

        kinds = [call[0] for call in self.recorder.calls]
        self.assertEqual(kinds, ["warning"])
        self.assertIn("无法写入", self.recorder.calls[-1][2])


if __name__ == "__main__":
    unittest.main()
