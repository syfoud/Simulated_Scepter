"""验证三种运行模式在失焦、窗口移动和尺寸改变时拒绝旧截图。"""

import unittest
from unittest.mock import Mock, patch

from tool.utils.image_tool import load_all_images_from_directory

# tool.simul.utils 导入时经 tool.utils.predict 读取图片缓存，需先加载到内存。
load_all_images_from_directory()

import tool.currency.utils as currency_utils
import tool.diver.utils as diver_utils
import tool.simul.utils as simul_utils
from tool.utils.game_window import LOCAL_WINDOW_KIND, CaptureGeometry, GameWindow

GAME_HWND = 12345
GAME_SIZE = (3840, 2160)


def make_window(hwnd=GAME_HWND, size=GAME_SIZE):
    return GameWindow(hwnd, LOCAL_WINDOW_KIND, "崩坏：星穹铁道", "UnityWndClass", size[0], size[1])


class GetScreenGuardCases:
    """三种模式共用的守卫用例，子类指定被测模块与工具类。"""

    module_path = None
    utils_cls = None

    def make_utils(self):
        """绕过 __init__（置前台、初始化 OCR 等），只准备 get_screen 读取的字段。"""
        utils = object.__new__(self.utils_cls)
        utils.game_hwnd = GAME_HWND
        utils.game_size = GAME_SIZE
        utils.capture_geometry = CaptureGeometry(0, 0, 3840, 2160, 3840, 2160, True)
        utils.last_get_screen_time = None
        utils.fps_list = []
        utils.sct = Mock()
        utils.x0 = 0
        utils.y0 = 0
        return utils

    def assert_rejected(self, window):
        """守卫拒绝时应抛 RuntimeError，且不进行任何截图。"""
        utils = self.make_utils()
        with patch("tool.utils.game_window.get_foreground_game_window", return_value=window):
            with self.assertRaisesRegex(RuntimeError, "失去前台"):
                utils.get_screen()
        utils.sct.grab.assert_not_called()
        self.assertFalse(hasattr(utils, "screen"))

    def test_no_foreground_game_window(self):
        self.assert_rejected(None)

    def test_foreground_hwnd_mismatch(self):
        # 前台是另一个游戏窗口实例，句柄与本模式记录的不一致。
        self.assert_rejected(make_window(hwnd=GAME_HWND + 1))

    def test_foreground_client_size_changed(self):
        # 前台仍是原窗口但客户区尺寸已变化，旧截图区域不再有效。
        self.assert_rejected(make_window(size=(1920, 1080)))

    def test_foreground_game_window_passes_capture(self):
        utils = self.make_utils()
        frame = object()
        utils.sct.grab.return_value = frame
        with patch("tool.utils.game_window.get_foreground_game_window", return_value=make_window()), patch(
            "tool.utils.game_window.get_window_rect", return_value=(0, 0, 3840, 2160)
        ):
            result = utils.get_screen()
        utils.sct.grab.assert_called_once_with(0, 0)
        self.assertIs(result, frame)
        self.assertIs(utils.screen, frame)

    def test_moved_window_never_reaches_capture(self):
        utils = self.make_utils()
        with patch("tool.utils.game_window.get_foreground_game_window", return_value=make_window()), patch(
            "tool.utils.game_window.get_window_rect", return_value=(100, 80, 3940, 2240)
        ):
            with self.assertRaisesRegex(RuntimeError, "位置"):
                utils.get_screen()
        utils.sct.grab.assert_not_called()
        self.assertFalse(hasattr(utils, "screen"))

    def test_capture_error_propagates_without_replacing_frame(self):
        utils = self.make_utils()
        utils.sct.grab.side_effect = RuntimeError("截图失败")
        previous = object()
        utils.screen = previous
        with patch("tool.utils.game_window.get_foreground_game_window", return_value=make_window()), patch(
            "tool.utils.game_window.get_window_rect", return_value=(0, 0, 3840, 2160)
        ):
            with self.assertRaisesRegex(RuntimeError, "截图失败"):
                utils.get_screen()
        self.assertIs(utils.screen, previous)


class SimulGetScreenGuardTests(GetScreenGuardCases, unittest.TestCase):
    module_path = "tool.simul.utils"
    utils_cls = simul_utils.UniverseUtils


class DiverGetScreenGuardTests(GetScreenGuardCases, unittest.TestCase):
    module_path = "tool.diver.utils"
    utils_cls = diver_utils.UniverseUtils


class CurrencyGetScreenGuardTests(GetScreenGuardCases, unittest.TestCase):
    module_path = "tool.currency.utils"
    utils_cls = currency_utils.CurrencyUtils


if __name__ == "__main__":
    unittest.main()
