"""敌人准星检测（红色连通块初筛 + 220×220 裁剪霍夫 + 并行右侧检测）的单元测试。

真实准星依赖游戏画面，这里用合成掩膜和打桩的霍夫结果验证几何/校验/坐标换算，
不截图、不开窗口、不依赖游戏。
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from tool.utils import predict as aim  # noqa: E402


def make_ring_mask(size=140, center=(70, 70), radius=30, thickness=2):
    """生成只有一圈白环的二值掩膜，用于覆盖率测试。"""
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.circle(mask, center, radius, 255, thickness)
    return mask


class RingCoverageTest(unittest.TestCase):
    def test_full_ring_is_covered(self):
        mask = make_ring_mask()
        self.assertGreater(aim._ring_coverage(mask, (70, 70), 30), 0.9)

    def test_empty_mask_is_not_covered(self):
        mask = np.zeros((140, 140), dtype=np.uint8)
        self.assertLess(aim._ring_coverage(mask, (70, 70), 30), 0.1)

    def test_radius_offset_is_tolerated(self):
        mask = make_ring_mask()
        # 霍夫半径有 ±1~2 px 误差，±2 的采样带应仍能覆盖大部分角度
        self.assertGreater(aim._ring_coverage(mask, (70, 70), 28), 0.7)

    def test_threshold_argument(self):
        mask = make_ring_mask()
        redness = mask.astype(np.int16)
        # 阈值高于像素值时应判定为未覆盖
        self.assertLess(aim._ring_coverage(redness, (70, 70), 30, 300), 0.1)
        self.assertGreater(aim._ring_coverage(redness, (70, 70), 30, 100), 0.9)


class CenterRednessTest(unittest.TestCase):
    def test_red_center(self):
        redness = np.zeros((120, 120), dtype=np.int16)
        redness[50:71, 50:71] = 120
        self.assertGreater(aim._center_redness(redness, (60, 60), 40), 100)

    def test_neutral_center(self):
        redness = np.zeros((120, 120), dtype=np.int16)
        self.assertLess(aim._center_redness(redness, (60, 60), 40), 10)


class SceneryRejectTest(unittest.TestCase):
    def test_horizontal_red_bar_is_rejected(self):
        glow = np.zeros((401, 401), dtype=np.uint8)
        glow[195:206, 0:400] = 255
        self.assertTrue(aim._is_horizontal_red_scenery(glow, (200, 200)))

    def test_ring_is_not_scenery(self):
        glow = np.zeros((401, 401), dtype=np.uint8)
        cv2.circle(glow, (200, 200), 30, 255, 2)
        self.assertFalse(aim._is_horizontal_red_scenery(glow, (200, 200)))


class HoughCropTest(unittest.TestCase):
    def test_circle_is_mapped_back_to_full_frame(self):
        white = np.zeros((300, 300), dtype=np.uint8)
        fake = np.array([[[110.0, 110.0, 30.0]]], dtype=np.float32)
        with patch.object(aim.cv2, "HoughCircles", return_value=fake):
            circles = aim._hough_in_crop(white, (150, 150))
        # 裁剪原点 = (150-110, 150-110) = (40, 40)
        self.assertEqual(circles, [(150, 150, 30)])

    def test_no_circles_returns_empty(self):
        white = np.zeros((300, 300), dtype=np.uint8)
        with patch.object(aim.cv2, "HoughCircles", return_value=None):
            self.assertEqual(aim._hough_in_crop(white, (150, 150)), [])


class ParallelPredictTest(unittest.TestCase):
    def test_main_hit_takes_priority(self):
        main_result = ({"enemy": (10, 20), "item": None}, None, None)
        with patch.object(aim, "_predict_main", return_value=main_result), \
                patch.object(aim, "predict_right", return_value=(500, 600)):
            self.assertEqual(aim.predict(np.zeros((1080, 1920, 3), np.uint8))["enemy"], (10, 20))

    def test_main_miss_uses_right_point(self):
        main_result = ({"enemy": None, "item": None}, None, None)
        with patch.object(aim, "_predict_main", return_value=main_result), \
                patch.object(aim, "predict_right", return_value=(500, 600)):
            self.assertEqual(aim.predict(np.zeros((1080, 1920, 3), np.uint8))["enemy"], (500, 600))

    def test_both_miss_returns_none(self):
        main_result = ({"enemy": None, "item": None}, None, None)
        with patch.object(aim, "_predict_main", return_value=main_result), \
                patch.object(aim, "predict_right", return_value=None):
            self.assertIsNone(aim.predict(np.zeros((1080, 1920, 3), np.uint8))["enemy"])

    def test_enemy_false_skips_right(self):
        main_result = ({"enemy": None, "item": None}, None, None)
        with patch.object(aim, "_predict_main", return_value=main_result) as main_mock, \
                patch.object(aim, "predict_right") as right_mock:
            aim.predict(np.zeros((1080, 1920, 3), np.uint8), enemy=False)
        main_mock.assert_called_once()
        right_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
