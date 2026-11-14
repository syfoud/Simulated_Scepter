"""后台窗口截屏：后端选择、WGC 适配与 PrintWindow 抓取真实窗口。"""

import os
import time
import unittest
from unittest.mock import patch

import numpy as np

from tool.screenshot import (
    CAPTURE_BACKENDS,
    PrintWindowCapture,
    WgcScreen,
    resolve_capture_backend,
)


class ResolveCaptureBackendTests(unittest.TestCase):
    def test_auto_follows_mode(self):
        self.assertEqual(resolve_capture_backend({}, False), "screen")
        self.assertEqual(resolve_capture_backend({}, True), "printwindow")

    def test_explicit_backend_wins_over_mode(self):
        for backend in CAPTURE_BACKENDS:
            with self.subTest(backend=backend):
                self.assertEqual(
                    resolve_capture_backend({"capture_backend": backend}, not backend == "screen"),
                    backend,
                )

    def test_unknown_backend_falls_back_to_mode_default(self):
        self.assertEqual(resolve_capture_backend({"capture_backend": "bogus"}, True), "printwindow")
        self.assertEqual(resolve_capture_backend({"capture_backend": "bogus"}, False), "screen")


class FakeWgcCapture:
    """替代录屏的 WGC 会话，只验证适配层的取帧与尺寸校验。"""

    width = 64
    height = 32
    started = False

    def __init__(self, hwnd, region, interval):
        self.hwnd = hwnd
        self.region = region
        self.interval = interval
        self.stopped = False
        FakeWgcCapture.started = True

    def start(self):
        pass

    def read_latest(self):
        return np.zeros((self.height, self.width, 3), np.uint8)

    def stop(self):
        self.stopped = True


class WgcScreenTests(unittest.TestCase):
    def test_adapter_returns_latest_frame_and_stops_capture(self):
        FakeWgcCapture.width, FakeWgcCapture.height = 64, 32
        with patch("tool.window_recorder.wgc_capture.WgcCapture", FakeWgcCapture), \
                patch("tool.screenshot.get_client_screen_rect", return_value=(0, 0, 64, 32)):
            screen = WgcScreen(7, 64, 32)
            frame = screen.grab()
            self.assertEqual(frame.shape, (32, 64, 3))
            screen.close()
        self.assertTrue(FakeWgcCapture.started)

    def test_size_mismatch_stops_capture_and_raises(self):
        instance = []

        class Capture(FakeWgcCapture):
            def __init__(self, hwnd, region, interval):
                super().__init__(hwnd, region, interval)
                instance.append(self)

        FakeWgcCapture.width, FakeWgcCapture.height = 32, 16
        with patch("tool.window_recorder.wgc_capture.WgcCapture", Capture), \
                patch("tool.screenshot.get_client_screen_rect", return_value=(0, 0, 32, 16)):
            with self.assertRaisesRegex(ValueError, "客户区"):
                WgcScreen(7, 64, 32)
        self.assertTrue(instance and instance[0].stopped)


class PrintWindowCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
            raise unittest.SkipTest("offscreen 平台没有真实窗口，无法验证 PrintWindow")
        from PyQt5.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, color, size=(320, 200)):
        from PyQt5.QtGui import QColor, QPalette
        from PyQt5.QtWidgets import QWidget

        window = QWidget()
        self.addCleanup(window.close)
        palette = window.palette()
        palette.setColor(QPalette.Window, QColor(*color))
        window.setAutoFillBackground(True)
        window.setPalette(palette)
        window.resize(*size)
        window.show()
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.01)
        return window

    def test_captures_client_area_of_a_real_window(self):
        from tool.utils.game_window import get_client_size

        window = self.make_window((51, 102, 204))
        hwnd = int(window.winId())
        width, height = get_client_size(hwnd)
        capture = PrintWindowCapture(hwnd, width, height)
        self.addCleanup(capture.close)

        frame = capture.grab()

        self.assertEqual(frame.shape, (height, width, 3))
        blue, green, red = (int(value) for value in frame[height // 2, width // 2])
        self.assertLess(abs(blue - 204), 40)
        self.assertLess(abs(green - 102), 40)
        self.assertLess(abs(red - 51), 40)

    def test_client_size_change_raises_instead_of_misreading(self):
        from tool.utils.game_window import get_client_size

        window = self.make_window((10, 20, 30))
        hwnd = int(window.winId())
        width, height = get_client_size(hwnd)
        capture = PrintWindowCapture(hwnd, width, height)
        self.addCleanup(capture.close)

        window.resize(width + 40, height + 30)
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.01)

        with self.assertRaisesRegex(RuntimeError, "客户区"):
            capture.grab()

    @classmethod
    def tearDownClass(cls):
        cls.app.processEvents()


if __name__ == "__main__":
    unittest.main()
