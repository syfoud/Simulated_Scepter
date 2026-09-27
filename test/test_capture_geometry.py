"""截图物理区域与 1080p 识别坐标的映射。"""

import ctypes
import sys
import types
import unittest
from unittest.mock import Mock, patch

# 本模块只验证纯几何计算；macOS 上提供 Win32 导入占位以便离线运行。
if sys.platform != "win32":
    sys.modules.setdefault("win32con", types.ModuleType("win32con"))
    sys.modules.setdefault("win32gui", types.ModuleType("win32gui"))

from tool.utils.game_window import (
    CLOUD_WINDOW_KIND,
    LOCAL_WINDOW_KIND,
    CaptureGeometry,
    GameWindow,
    get_capture_geometry,
    set_process_dpi_awareness,
    validate_capture_geometry,
)


def make_window(kind, width, height):
    return GameWindow(1, kind, "game", "class", width, height)


class CaptureGeometryTests(unittest.TestCase):
    def test_local_1080p_keeps_client_coordinates(self):
        with patch("tool.utils.game_window.get_window_rect", return_value=(100, 80, 2020, 1160)):
            geometry = get_capture_geometry(make_window(LOCAL_WINDOW_KIND, 1920, 1080))
        self.assertEqual((geometry.left, geometry.top, geometry.right, geometry.bottom), (100, 80, 2020, 1160))
        self.assertEqual((geometry.width, geometry.height), (1920, 1080))
        self.assertEqual((geometry.scale_x, geometry.scale_y), (1.0, 1.0))
        self.assertFalse(geometry.full)

    def test_local_4k_uses_full_physical_frame(self):
        with patch("tool.utils.game_window.get_window_rect", return_value=(0, 0, 3840, 2160)):
            geometry = get_capture_geometry(make_window(LOCAL_WINDOW_KIND, 3840, 2160))
        self.assertEqual((geometry.left, geometry.top, geometry.right, geometry.bottom), (0, 0, 3840, 2160))
        self.assertEqual((geometry.scale_x, geometry.scale_y), (2.0, 2.0))
        self.assertTrue(geometry.full)

    def test_other_large_16_9_resolutions_remain_unsupported(self):
        for width, height in ((2560, 1440), (3840, 2150), (7680, 4320)):
            with self.subTest(size=(width, height)), patch(
                "tool.utils.game_window.get_window_rect", return_value=(0, 0, width, height)
            ):
                self.assertIsNone(get_capture_geometry(make_window(LOCAL_WINDOW_KIND, width, height)))

    def test_legacy_single_axis_crop(self):
        with patch("tool.utils.game_window.get_window_rect", return_value=(0, 0, 2560, 1080)):
            geometry = get_capture_geometry(make_window(LOCAL_WINDOW_KIND, 2560, 1080))
        self.assertEqual((geometry.left, geometry.top, geometry.right, geometry.bottom), (320, 0, 2240, 1080))
        self.assertEqual((geometry.width, geometry.height), (1920, 1080))

    def test_rejects_other_ratios_before_normalizing(self):
        with patch("tool.utils.game_window.get_window_rect", return_value=(0, 0, 3000, 2000)):
            geometry = get_capture_geometry(make_window(LOCAL_WINDOW_KIND, 3000, 2000))
        self.assertIsNone(geometry)

    def test_rejects_failed_frame_measurement(self):
        with patch("tool.utils.game_window.get_window_rect", return_value=(0, 0, 0, 0)):
            geometry = get_capture_geometry(make_window(LOCAL_WINDOW_KIND, 3840, 2160))
        self.assertIsNone(geometry)

    def test_cloud_keeps_1080p_capture_with_frame_tolerance(self):
        with patch("tool.utils.game_window.get_client_screen_rect", return_value=(50, 40, 1978, 1128)):
            geometry = get_capture_geometry(make_window(CLOUD_WINDOW_KIND, 1928, 1088))
        self.assertEqual((geometry.left, geometry.top, geometry.right, geometry.bottom), (50, 40, 1970, 1120))
        self.assertEqual((geometry.scale_x, geometry.scale_y), (1.0, 1.0))
        self.assertFalse(geometry.full)

    def test_negative_monitor_coordinates_are_preserved(self):
        with patch("tool.utils.game_window.get_window_rect", return_value=(-3840, 0, 0, 2160)):
            geometry = get_capture_geometry(make_window(LOCAL_WINDOW_KIND, 3840, 2160))
        self.assertEqual((geometry.left, geometry.top), (-3840, 0))


class DpiAwarenessTests(unittest.TestCase):
    def test_per_monitor_v2_is_preferred(self):
        windows = Mock()
        windows.user32.SetProcessDpiAwarenessContext.return_value = 1
        with patch("tool.utils.game_window.ctypes.windll", windows, create=True):
            self.assertTrue(set_process_dpi_awareness())
        context = windows.user32.SetProcessDpiAwarenessContext.call_args.args[0]
        self.assertEqual(context.value, ctypes.c_void_p(-4).value)
        windows.shcore.SetProcessDpiAwareness.assert_not_called()
        windows.user32.SetProcessDPIAware.assert_not_called()

    def test_legacy_fallback_is_used_when_modern_api_fails(self):
        windows = Mock()
        windows.user32.SetProcessDpiAwarenessContext.side_effect = OSError("unsupported")
        windows.shcore.SetProcessDpiAwareness.side_effect = OSError("unsupported")
        windows.user32.SetProcessDPIAware.return_value = 1
        with patch("tool.utils.game_window.ctypes.windll", windows, create=True):
            self.assertTrue(set_process_dpi_awareness())
        windows.user32.SetProcessDPIAware.assert_called_once_with()

    def test_failed_awareness_request_is_reported(self):
        windows = Mock()
        windows.user32.SetProcessDpiAwarenessContext.return_value = 0
        windows.shcore.SetProcessDpiAwareness.return_value = 1
        windows.user32.SetProcessDPIAware.return_value = 0
        with patch("tool.utils.game_window.ctypes.windll", windows, create=True):
            self.assertFalse(set_process_dpi_awareness())


class CaptureGuardTests(unittest.TestCase):
    def test_unchanged_geometry_is_allowed(self):
        window = make_window(LOCAL_WINDOW_KIND, 3840, 2160)
        geometry = CaptureGeometry(0, 0, 3840, 2160, 3840, 2160, True)
        with patch("tool.utils.game_window.get_foreground_game_window", return_value=window), patch(
            "tool.utils.game_window.get_window_rect", return_value=(0, 0, 3840, 2160)
        ):
            validate_capture_geometry(1, (3840, 2160), geometry)

    def test_moved_window_is_rejected_even_if_size_matches(self):
        for kind in (LOCAL_WINDOW_KIND, CLOUD_WINDOW_KIND):
            width, height = (3840, 2160) if kind == LOCAL_WINDOW_KIND else (1920, 1080)
            window = make_window(kind, width, height)
            geometry = CaptureGeometry(0, 0, width, height, width, height, True)
            with self.subTest(kind=kind), patch(
                "tool.utils.game_window.get_foreground_game_window", return_value=window
            ), patch("tool.utils.game_window.get_window_rect", return_value=(100, 80, width + 100, height + 80)), patch(
                "tool.utils.game_window.get_client_screen_rect", return_value=(100, 80, width + 100, height + 80)
            ):
                with self.assertRaisesRegex(RuntimeError, "位置"):
                    validate_capture_geometry(1, (width, height), geometry)

    def test_missing_window_other_instance_and_resize_are_rejected(self):
        geometry = CaptureGeometry(0, 0, 3840, 2160, 3840, 2160, True)
        other = GameWindow(2, LOCAL_WINDOW_KIND, "game", "class", 3840, 2160)
        for window in (None, other, make_window(LOCAL_WINDOW_KIND, 1920, 1080)):
            with self.subTest(window=window), patch(
                "tool.utils.game_window.get_foreground_game_window", return_value=window
            ):
                with self.assertRaisesRegex(RuntimeError, "失去前台"):
                    validate_capture_geometry(1, (3840, 2160), geometry)


if __name__ == "__main__":
    unittest.main()
