"""调试识别遮罩：状态机发布命中的状态与位置，遮罩在游戏画面坐标系里画出红框。"""

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QImage, QPainter  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from core.common.engine import StateKernel  # noqa: E402
from tool import GLOBAL  # noqa: E402
from tool.debug_overlay import DebugOverlay, overlay_signal, publish_match  # noqa: E402
from tool.mask import union_boxes  # noqa: E402


class UnionBoxesTest(unittest.TestCase):
    def test_boxes_are_merged_into_one_outer_frame(self):
        self.assertEqual(union_boxes([[10, 20, 30, 40], [5, 25, 50, 35]]), [5, 20, 50, 40])


class PublishMatchTest(unittest.TestCase):
    def setUp(self):
        self.received = []

    def receive(self, name, box):
        self.received.append((name, box))

    def connect(self):
        overlay_signal.match_signal.connect(self.receive)
        self.addCleanup(overlay_signal.match_signal.disconnect, self.receive)

    def test_non_debug_mode_publishes_nothing(self):
        self.connect()
        with patch.object(GLOBAL, "DEBUG_MODE", False):
            publish_match("选择祝福", [1, 2, 3, 4])
        self.assertEqual(self.received, [])

    def test_debug_mode_publishes_state_and_box(self):
        self.connect()
        with patch.object(GLOBAL, "DEBUG_MODE", True):
            publish_match("选择祝福", [1, 2, 3, 4])
        self.assertEqual(self.received, [("选择祝福", [1, 2, 3, 4])])

    def test_worker_thread_publish_reaches_the_ui_thread(self):
        """状态机在任务线程运行，命中结果必须排队回界面线程才能落到遮罩上。"""
        self.connect()
        thread = threading.Thread(target=publish_match, args=("选择祝福", [1, 2, 3, 4]))
        with patch.object(GLOBAL, "DEBUG_MODE", True):
            thread.start()
            deadline = time.monotonic() + 3
            while not self.received and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
            thread.join()
        self.assertEqual(self.received, [("选择祝福", [1, 2, 3, 4])])


class MatchActionsPublishTest(unittest.TestCase):
    """状态机只负责发布命中结果，是否画出来由遮罩按调试模式决定。"""

    def setUp(self):
        self.kernel = StateKernel()
        self.kernel.ts = Mock()
        self.kernel.check = Mock(return_value=True)
        self.kernel.click_target = Mock(return_value=True)
        self.kernel.do_action = Mock(return_value=None)
        self.published = []
        self.enterContext(patch("core.common.engine.publish_match",
                                lambda name, box: self.published.append((name, box))))

    def run_actions(self, **trigger):
        actions = {"界面": [{"name": "选择祝福", "trigger": trigger, "actions": []}]}
        self.kernel.match_actions(json_file=actions)

    def matched_at(self, box):
        """让 check/click_target 假装在 box 处命中，并像真实实现一样记下落框。"""
        def fake(*_args, **_kwargs):
            self.kernel.tb = box
            return True
        return fake

    def test_text_trigger_publishes_recognized_box(self):
        self.kernel.ts.find_with_box.return_value = [{"raw_text": "选择祝福", "box": [98, 59, 202, 95]}]
        self.run_actions(text="选择祝福", box=[98, 59, 202, 95])
        self.assertEqual(self.published, [("选择祝福", [98, 59, 202, 95])])

    def test_located_photo_trigger_publishes_matched_frame(self):
        self.kernel.check.side_effect = self.matched_at([100, 200, 300, 260])
        self.run_actions(photo="button", pos={"x": 1, "y": 2})
        self.assertEqual(self.published, [("选择祝福", [100, 200, 300, 260])])

    def test_global_photo_trigger_publishes_frame_recorded_by_click_target(self):
        self.kernel.click_target.side_effect = self.matched_at([10, 20, 30, 40])
        self.run_actions(photo="herta_office")
        self.assertEqual(self.published, [("选择祝福", [10, 20, 30, 40])])

    def test_state_only_trigger_publishes_without_position(self):
        self.kernel.update_state("done")
        self.run_actions(state_only=True, condition="done")
        self.assertEqual(self.published, [("选择祝福", None)])

    def test_unmatched_screen_publishes_nothing(self):
        self.kernel.ts.find_with_box.return_value = []
        self.run_actions(text="选择祝福", box=[98, 59, 202, 95])
        self.assertEqual(self.published, [])

    def test_state_is_published_even_when_once_has_already_fired(self):
        self.kernel.ts.find_with_box.return_value = [{"raw_text": "选择祝福", "box": [1, 2, 3, 4]}]
        self.run_actions(text="选择祝福", box=[1, 2, 3, 4], once=True)
        self.run_actions(text="选择祝福", box=[1, 2, 3, 4], once=True)
        # 第一次执行动作，第二次被 once 挡下，两次都识别到了这个状态
        self.assertEqual(self.published, [("选择祝福", [1, 2, 3, 4])] * 2)


class DebugOverlayTest(unittest.TestCase):
    def setUp(self):
        QApplication.instance() or QApplication([])
        self.enterContext(patch("tool.debug_overlay.find_game_window", return_value=None))
        self.overlay = DebugOverlay()
        self.enterContext(patch.object(self.overlay, "show"))
        self.enterContext(patch.object(self.overlay, "raise_"))
        self.addCleanup(self.overlay.deleteLater)

    def test_newest_state_replaces_its_previous_mark(self):
        with patch("tool.debug_overlay.time.monotonic", return_value=100.0):
            self.overlay.add_mark("选择祝福", [1, 2, 3, 4])
            self.overlay.add_mark("选择祝福", [5, 6, 7, 8])
        self.assertEqual([mark["box"] for mark in self.overlay.marks], [[5, 6, 7, 8]])

    def test_expired_marks_are_dropped(self):
        with patch("tool.debug_overlay.time.monotonic", return_value=100.0):
            self.overlay.add_mark("选择祝福", [1, 2, 3, 4])
        with patch("tool.debug_overlay.time.monotonic", return_value=102.0):
            self.overlay.expire()
        self.assertEqual(self.overlay.marks, [])

    def test_window_lookup_failure_disables_overlay_instead_of_raising(self):
        """遮罩只是调试显示：定位游戏窗口失败时停用，异常不能传进 Qt 槽。"""
        with patch("tool.debug_overlay.find_game_window", side_effect=OSError("窗口已关闭")), \
                patch("tool.debug_overlay.CUS_LOGGER") as logger:
            self.overlay.add_mark("选择祝福", [1, 2, 3, 4])
        self.assertFalse(self.overlay.available)
        self.assertEqual(self.overlay.marks, [])
        logger.warning.assert_called_once()
        # 停用之后不再尝试定位游戏窗口
        with patch("tool.debug_overlay.find_game_window") as window:
            self.overlay.add_mark("出战", None)
        window.assert_not_called()

    def test_overlay_covers_game_client_area_and_scales_boxes(self):
        with patch("tool.debug_overlay.find_game_window", return_value=SimpleNamespace(hwnd=123)), \
                patch("tool.debug_overlay.ui_client_rect", return_value=(100, 200, 960, 540)):
            self.overlay.add_mark("选择祝福", [0, 0, 1920, 1080])
        self.assertEqual(
            (self.overlay.x(), self.overlay.y(), self.overlay.width(), self.overlay.height()),
            (100, 200, 960, 540),
        )
        self.assertEqual((self.overlay.scale_x, self.overlay.scale_y), (0.5, 0.5))

    def test_paint_draws_red_frame_at_scaled_position(self):
        self.overlay.add_mark("选择祝福", [100, 200, 300, 260])
        self.overlay.scale_x = self.overlay.scale_y = 0.5
        self.overlay.resize(960, 540)
        image = self.render_overlay()
        # 识别框 [100, 200, 300, 260] 缩放一半后框住 (50, 100)-(150, 130)
        self.assertTrue(self.has_red_pixel(image, 46, 96, 56, 106), "识别框左边没画出来")
        self.assertTrue(self.has_red_pixel(image, 146, 126, 156, 136), "识别框右下角没画出来")

    def test_state_without_position_is_labeled_at_top_center(self):
        self.overlay.add_mark("出战", None)
        self.overlay.resize(960, 540)
        image = self.render_overlay()
        # offscreen 平台没有字体、画不出字形，这里只验证标签底框的位置：贴着画面顶部并居中
        xs = [x for x in range(image.width()) for y in range(40)
              if image.pixelColor(x, y).alpha()]
        self.assertTrue(xs, "纯状态命中的标签没画在顶部")
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, image.width() / 2, delta=2)

    def render_overlay(self):
        image = QImage(self.overlay.width(), self.overlay.height(), QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        try:
            self.overlay.render(painter)
        finally:
            painter.end()
        return image

    @staticmethod
    def has_red_pixel(image, left, top, right, bottom):
        """区域内是否存在红框/红字像素；抗锯齿边缘也算，只要红色明显高于绿蓝。"""
        for x in range(max(0, left), min(image.width(), right)):
            for y in range(max(0, top), min(image.height(), bottom)):
                color = image.pixelColor(x, y)
                if color.red() > 150 and color.green() < 90 and color.blue() < 90:
                    return True
        return False


if __name__ == "__main__":
    unittest.main()
