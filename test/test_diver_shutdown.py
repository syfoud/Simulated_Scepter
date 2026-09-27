"""差分宇宙直接键盘通道的停止与按键释放。"""

import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch


class DiverKeyopsTests(unittest.TestCase):
    def setUp(self):
        fake_pyautogui = types.ModuleType("pyautogui")
        fake_pyautogui.keyDown = MagicMock()
        fake_pyautogui.keyUp = MagicMock()
        fake_config_module = types.ModuleType("tool.diver.config")
        fake_config_module.config = types.SimpleNamespace(
            origin_key=["w", "shift", "f"],
            mapping=["up", "shiftleft", "f"],
            long_press_sprint=1,
        )
        path = Path(__file__).resolve().parents[1] / "tool" / "diver" / "keyops.py"
        spec = importlib.util.spec_from_file_location("test_diver_keyops_module", path)
        self.keyops = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"pyautogui": fake_pyautogui, "tool.diver.config": fake_config_module}):
            spec.loader.exec_module(self.keyops)
        self.pyautogui = fake_pyautogui

    def test_stop_releases_mapped_keys_and_is_idempotent(self):
        self.keyops.keyDown("w")
        self.keyops.keyDown("shift")

        self.assertEqual(self.keyops.release_pressed_keys(), {})
        self.assertCountEqual(self.pyautogui.keyUp.call_args_list, [call("up"), call("shiftleft")])
        self.assertEqual(self.keyops.release_pressed_keys(), {})
        self.assertEqual(self.pyautogui.keyUp.call_count, 2)

    def test_failed_release_remains_tracked_for_retry(self):
        self.keyops.keyDown("w")
        self.pyautogui.keyUp.side_effect = RuntimeError("input failed")

        failures = self.keyops.release_pressed_keys()
        self.assertEqual(tuple(failures), ("up",))
        self.assertIsInstance(failures["up"], RuntimeError)

        self.pyautogui.keyUp.side_effect = None
        self.assertEqual(self.keyops.release_pressed_keys(), {})
        self.assertEqual(self.keyops.release_pressed_keys(), {})
        self.assertEqual(self.pyautogui.keyUp.call_count, 2)

    def test_long_press_sprint_releases_shift_with_forward_key(self):
        self.keyops.keyDown("w")
        self.keyops.keyDown("shift")

        self.keyops.keyUp("w")

        self.assertEqual(self.pyautogui.keyUp.call_args_list, [call("shiftleft"), call("up")])
        self.assertEqual(self.keyops.release_pressed_keys(), {})
        self.assertEqual(self.pyautogui.keyUp.call_count, 2)

    def test_key_controller_finishes_pressed_f_before_join_returns(self):
        pressed = threading.Event()
        self.pyautogui.keyDown.side_effect = lambda key: pressed.set()
        father = types.SimpleNamespace(_stop=False)
        controller = self.keyops.KeyController(father)
        try:
            controller.fff = 1
            self.assertTrue(pressed.wait(1))
        finally:
            father._stop = True
            controller.join()

        self.assertFalse(controller.thread.is_alive())
        self.assertIn(call("f"), self.pyautogui.keyUp.call_args_list)
        self.assertEqual(self.keyops.release_pressed_keys(), {})
        self.assertEqual(self.pyautogui.keyUp.call_count, 1)


if __name__ == "__main__":
    unittest.main()
