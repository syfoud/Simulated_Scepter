"""校验坐标换算：屏幕物理像素 → 1920x1080 基准。"""

import unittest

from tool.coordinate_picker import format_point, to_base


class TestCoordinatePicker(unittest.TestCase):
    def test_same_size_window_is_identity(self):
        rect = (100, 50, 2020, 1130)  # 正好 1920x1080
        self.assertEqual(to_base(100, 50, rect), (0, 0))
        self.assertEqual(to_base(1060, 590, rect), (960, 540))
        self.assertEqual(to_base(2020, 1130, rect), (1920, 1080))

    def test_scaled_window_maps_to_base(self):
        rect = (0, 0, 3840, 2160)  # 两倍缩放
        self.assertEqual(to_base(1920, 1080, rect), (960, 540))
        self.assertEqual(to_base(0, 0, rect), (0, 0))

    def test_invalid_rect_raises(self):
        with self.assertRaises(ValueError):
            to_base(0, 0, (0, 0, 0, 0))

    def test_format_point_contains_all_three_systems(self):
        text = format_point((0, 0), (100, 50), (100, 50, 2020, 1130))
        self.assertIn("(0, 0)", text)
        self.assertIn("窗口内 (0, 0)", text)
        self.assertIn("屏幕 (100, 50)", text)


if __name__ == "__main__":
    unittest.main()
