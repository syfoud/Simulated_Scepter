"""差分宇宙 click_target 重写后的契约：达标点击、超时、阈值下限与停止。"""

import unittest
from unittest.mock import Mock, patch

import numpy as np

from tool.diver.utils import UniverseUtils


class DiverClickTargetTests(unittest.TestCase):
    def setUp(self):
        # click_target 的 target_path 实为已加载的模板图像（find_image_by_name 返回 ndarray）
        self.target = np.zeros((20, 30, 3), dtype=np.uint8)

    def make_utils(self, max_val):
        utils = object.__new__(UniverseUtils)
        utils._stop = False
        utils.sct = Mock()
        utils.scan_screenshot = Mock(return_value={
            "screenshot": None,
            "min_val": 0.0,
            "max_val": max_val,
            "min_loc": (0, 0),
            "max_loc": (100, 40),
        })
        utils.click_position = Mock()
        return utils

    def test_matched_target_is_clicked_and_returns_true(self):
        utils = self.make_utils(max_val=0.95)

        result = utils.click_target(self.target, 0.9, click=True)

        self.assertTrue(result)
        utils.scan_screenshot.assert_called_once()
        # max_loc=(100, 40) 与模板 (20, 30, 3) 经 calculated() 得到的中心点
        utils.click_position.assert_called_once_with((115, 50))

    def test_unmatched_target_times_out_and_returns_false(self):
        utils = self.make_utils(max_val=0.5)
        # 首次调用算出 deadline，随后推进到 10 秒截止点；末尾大值保证超时数值被改大时也会退出而不是死循环
        times = iter([0.0, 1.0, 5.0, 9.9, 10.0, 1e9])

        with (
            patch("tool.diver.utils.time.monotonic", side_effect=lambda: next(times, 1e9)),
            patch("tool.diver.utils.time.sleep"),
        ):
            result = utils.click_target(self.target, 0.9, click=True)

        self.assertFalse(result)
        utils.click_position.assert_not_called()
        # 第 4 次扫描后才越过截止点：超时前持续重试，且不早于 9.9 秒放弃
        self.assertEqual(utils.scan_screenshot.call_count, 4)

    def test_threshold_decay_stops_at_floor(self):
        # (初始阈值, 略低于下限的匹配度, 略高于下限的匹配度, 达标时的扫描次数)
        # 下限为 max(0.85, threshold - 0.05)，每次衰减 0.01；0.87 一档由 0.85 钳位兜底
        cases = (
            (0.90, 0.848, 0.852, 6),
            (0.93, 0.878, 0.882, 6),
            (0.87, 0.848, 0.852, 3),
        )
        for threshold, below, above, scans in cases:
            with self.subTest(threshold=threshold):
                utils = self.make_utils(max_val=below)
                times = iter([0.0, 1.0, 2.0, 1e9])
                with (
                    patch("tool.diver.utils.time.monotonic", side_effect=lambda: next(times, 1e9)),
                    patch("tool.diver.utils.time.sleep"),
                ):
                    self.assertFalse(utils.click_target(self.target, threshold, click=True))
                utils.click_position.assert_not_called()

                utils = self.make_utils(max_val=above)
                with (
                    patch("tool.diver.utils.time.monotonic", return_value=0.0),
                    patch("tool.diver.utils.time.sleep"),
                ):
                    self.assertTrue(utils.click_target(self.target, threshold, click=True))
                self.assertEqual(utils.scan_screenshot.call_count, scans)
                utils.click_position.assert_called_once_with((115, 50))

    def test_stop_before_start_skips_scan_and_returns_false(self):
        utils = self.make_utils(max_val=0.95)
        utils._stop = True

        result = utils.click_target(self.target, 0.9, click=True)

        self.assertFalse(result)
        utils.scan_screenshot.assert_not_called()
        utils.click_position.assert_not_called()

    def test_stop_during_wait_exits_loop_and_returns_false(self):
        utils = self.make_utils(max_val=0.5)

        def stop_after_scan(*args, **kwargs):
            utils._stop = True
            return utils.scan_screenshot.return_value

        utils.scan_screenshot.side_effect = stop_after_scan

        with patch("tool.diver.utils.time.sleep"):
            result = utils.click_target(self.target, 0.9, click=True)

        self.assertFalse(result)
        # 置位后不再继续扫描：循环在下一次迭代开头退出，而不是等满超时
        utils.scan_screenshot.assert_called_once()
        utils.click_position.assert_not_called()

    def test_scan_uses_normalized_game_frame(self):
        utils = object.__new__(UniverseUtils)
        rng = np.random.default_rng(17)
        frame = rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
        target = frame[50:70, 100:130].copy()
        utils.get_screen = Mock(return_value=frame)
        utils.cap_scale = 2.0
        with patch("tool.diver.utils.pyautogui.screenshot") as desktop_capture:
            result = utils.scan_screenshot(target)
        utils.get_screen.assert_called_once_with()
        desktop_capture.assert_not_called()
        self.assertIs(result["screenshot"], frame)
        self.assertEqual(result["max_loc"], (100, 50))
        self.assertGreater(result["max_val"], 0.99)


if __name__ == "__main__":
    unittest.main()
