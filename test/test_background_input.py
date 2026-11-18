"""后台键盘通道：消息拼装、伪造激活、按键释放与键鼠管理器路由。"""

import time
import unittest
from unittest.mock import Mock, patch

import win32con

from tool.background_input import BackgroundKeyboard, key_lparam, scan_code
from tool.key_mouse_manager import KeyMouseManager


class KeyLayoutTests(unittest.TestCase):
    def test_game_keys_used_by_kernels_are_supported(self):
        for key in ("f", "1", "f4", "v", "space", "enter", "esc", "shiftleft", "ctrlright"):
            self.assertTrue(BackgroundKeyboard.supports(key), key)

    def test_logical_names_are_not_supported_before_resolving(self):
        self.assertFalse(BackgroundKeyboard.supports("interact"))

    def test_scan_code_matches_known_keyboard_layout(self):
        self.assertEqual(scan_code(0x46), 0x21)  # F

    def test_lparam_carries_scan_code_extended_and_release_flags(self):
        down = key_lparam(0x21, extended=False, key_up=False)
        self.assertEqual(down, 1 | (0x21 << 16))
        up = key_lparam(0x21, extended=False, key_up=True)
        self.assertEqual(up, down | (1 << 30) | (1 << 31))
        extended = key_lparam(0x1D, extended=True, key_up=False)
        self.assertEqual(extended, 1 | (0x1D << 16) | (1 << 24))
        sys_key = key_lparam(0x38, extended=False, key_up=False, sys_key=True)
        self.assertEqual(sys_key, 1 | (0x38 << 16) | (1 << 29))


class BackgroundKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.post = self.enterContext(patch("tool.background_input.win32gui.PostMessage"))
        self.foreground = self.enterContext(
            patch("tool.background_input.win32gui.GetForegroundWindow", return_value=999))
        self.set_foreground = self.enterContext(
            patch("tool.background_input.win32gui.SetForegroundWindow"))
        self.keyboard = BackgroundKeyboard(1234)

    def posts(self):
        return [call.args for call in self.post.call_args_list]

    def test_press_activates_game_posts_key_and_clears_activation(self):
        self.keyboard.press("f")
        down = key_lparam(scan_code(0x46), False, False)
        up = key_lparam(scan_code(0x46), False, True)
        self.assertEqual(self.posts(), [
            (1234, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0),
            (1234, win32con.WM_KEYDOWN, 0x46, down),
            (1234, win32con.WM_KEYUP, 0x46, up),
            (1234, win32con.WM_ACTIVATE, win32con.WA_INACTIVE, 0),
        ])

    def test_foreground_game_gets_no_fake_activation(self):
        self.foreground.return_value = 1234
        self.keyboard.press("f")
        messages = [call.args[1] for call in self.post.call_args_list]
        self.assertEqual(messages, [win32con.WM_KEYDOWN, win32con.WM_KEYUP])

    def test_alt_keys_use_system_key_messages(self):
        self.keyboard.press("altleft")
        messages = [call.args[1] for call in self.post.call_args_list]
        self.assertIn(win32con.WM_SYSKEYDOWN, messages)
        self.assertIn(win32con.WM_SYSKEYUP, messages)
        down = [call for call in self.post.call_args_list
                if call.args[1] == win32con.WM_SYSKEYDOWN][0]
        self.assertTrue(down.args[3] & (1 << 29))

    def test_held_keys_keep_activation_until_the_last_release(self):
        self.keyboard.key_down("f")
        self.keyboard.key_down("g")
        self.assertTrue(self.keyboard.activated)
        self.keyboard.key_up("f")
        self.assertTrue(self.keyboard.activated)
        self.keyboard.key_up("g")
        self.assertFalse(self.keyboard.activated)
        messages = [call.args[1] for call in self.post.call_args_list]
        self.assertEqual(messages.count(win32con.WM_ACTIVATE), 2)

    def test_press_duration_uses_interruptible_sleep(self):
        sleep = Mock()
        self.keyboard.press("f", duration=0.3, sleep=sleep)
        sleep.assert_called_once_with(0.3)

    def test_unsupported_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.keyboard.key_down("interact")
        self.post.assert_not_called()

    def test_release_all_releases_held_keys_and_activation(self):
        self.keyboard.key_down("f")
        self.keyboard.key_down("g")
        self.keyboard.release_all()
        self.assertEqual(self.keyboard.held, set())
        self.assertFalse(self.keyboard.activated)
        messages = [call.args[1] for call in self.post.call_args_list]
        self.assertEqual(messages.count(win32con.WM_KEYUP), 2)

    def test_game_stealing_foreground_is_restored(self):
        self.foreground.side_effect = [999, 1234]
        self.keyboard.press("f")
        self.set_foreground.assert_called_once_with(999)


class BackgroundMessageDeliveryTests(unittest.TestCase):
    """用真实窗口验证消息格式：游戏窗口收到按键，且这里不抢前台。"""

    @classmethod
    def setUpClass(cls):
        import os

        if os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
            raise unittest.SkipTest("offscreen 平台没有真实窗口")
        from PyQt5.QtWidgets import QApplication, QWidget

        cls.app = QApplication.instance() or QApplication([])

        class KeyProbe(QWidget):
            keys = []

            def keyPressEvent(self, event):
                self.keys.append(event.key())
                super().keyPressEvent(event)

        cls.window = KeyProbe()
        cls.window.show()
        for _ in range(20):
            cls.app.processEvents()
            time.sleep(0.01)

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def test_press_reaches_game_window_without_changing_foreground(self):
        import win32gui

        window = self.__class__.window
        window.keys = []
        before = win32gui.GetForegroundWindow()
        self.__class__.app.processEvents()
        keyboard = BackgroundKeyboard(int(window.winId()))
        keyboard.press("f")
        keyboard.press("esc")
        deadline = time.monotonic() + 3
        while len(window.keys) < 2 and time.monotonic() < deadline:
            self.__class__.app.processEvents()
            time.sleep(0.01)
        self.assertEqual(window.keys, [int(ord("F")), 0x01000000])
        self.assertEqual(win32gui.GetForegroundWindow(), before)


class KeyMouseManagerRoutingTests(unittest.TestCase):
    def setUp(self):
        self.manager = KeyMouseManager()
        self.manager.set_screen_params(1920, 1080, 1920, 1080)

    def test_press_is_sent_through_background_channel(self):
        background = Mock(spec=BackgroundKeyboard)
        background.supports.return_value = True
        self.manager.background = background
        self.manager._execute_operation(
            {"type": "press", "key": "f", "duration": 0.1, "allow_e": 1})
        background.press.assert_called_once()
        self.assertEqual(background.press.call_args.args[0], "f")

    def test_unsupported_key_is_skipped_instead_of_falling_back(self):
        background = Mock(spec=BackgroundKeyboard)
        background.supports.return_value = False
        self.manager.background = background
        with patch("tool.key_mouse_manager.pyautogui") as gui:
            self.manager._execute_operation(
                {"type": "press", "key": "f", "duration": 0, "allow_e": 1})
        background.press.assert_not_called()
        gui.keyDown.assert_not_called()

    def test_click_is_blocked_when_game_is_not_foreground(self):
        background = Mock(spec=BackgroundKeyboard)
        background.game_is_foreground.return_value = False
        self.manager.background = background
        with patch("tool.key_mouse_manager.pyautogui") as gui, \
                patch("tool.key_mouse_manager.win32api") as api:
            self.manager._execute_operation({"type": "click", "x": 100, "y": 100})
        api.SetCursorPos.assert_not_called()
        gui.click.assert_not_called()

    def test_foreground_mode_still_injects_with_pyautogui(self):
        with patch("tool.key_mouse_manager.pyautogui") as gui:
            self.manager._execute_operation(
                {"type": "press", "key": "f", "duration": 0, "allow_e": 1})
        gui.keyDown.assert_called_once_with("f")
        gui.keyUp.assert_called_once_with("f")

    def test_technique_can_still_be_skipped(self):
        background = Mock(spec=BackgroundKeyboard)
        self.manager.background = background
        self.manager._execute_operation(
            {"type": "press", "key": "technique", "duration": 0, "allow_e": 0})
        background.press.assert_not_called()

    def test_set_background_keyboard_toggles_channel(self):
        self.manager.set_background_keyboard(4321)
        self.assertIsInstance(self.manager.background, BackgroundKeyboard)
        self.manager.set_background_keyboard(None)
        self.assertIsNone(self.manager.background)


if __name__ == "__main__":
    unittest.main()
