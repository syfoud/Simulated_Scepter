import unittest

import cv2
import numpy as np

from tool.key_mouse_manager import KeyMouseManager
from tool.utils.game_window import (
    BASE_HEIGHT,
    BASE_WIDTH,
    CLOUD_WINDOW_KIND,
    LOCAL_WINDOW_KIND,
    is_supported_resolution,
)


class SupportedResolutionTests(unittest.TestCase):
    def test_local_base_resolution(self):
        self.assertTrue(is_supported_resolution(LOCAL_WINDOW_KIND, 1920, 1080))

    def test_local_4k_resolution(self):
        self.assertTrue(is_supported_resolution(LOCAL_WINDOW_KIND, 3840, 2160))
        self.assertFalse(is_supported_resolution(LOCAL_WINDOW_KIND, 2560, 1440))
        self.assertFalse(is_supported_resolution(LOCAL_WINDOW_KIND, 3840, 2150))
        self.assertFalse(is_supported_resolution(LOCAL_WINDOW_KIND, 7680, 4320))

    def test_local_rejects_unsupported_sizes(self):
        # 超宽屏（由 get_xy 裁剪分支处理，不视为 16:9 缩放目标）
        self.assertFalse(is_supported_resolution(LOCAL_WINDOW_KIND, 2560, 1080))
        self.assertFalse(is_supported_resolution(LOCAL_WINDOW_KIND, 1366, 768))
        self.assertFalse(is_supported_resolution(LOCAL_WINDOW_KIND, 1920, 1200))

    def test_cloud_tolerance_unchanged(self):
        self.assertTrue(is_supported_resolution(CLOUD_WINDOW_KIND, 1928, 1088))
        self.assertFalse(is_supported_resolution(CLOUD_WINDOW_KIND, 1940, 1080))


class CoordinateScalingTests(unittest.TestCase):
    def test_int_coordinates_scale_to_physical_pixels(self):
        manager = KeyMouseManager()
        # 4K 全屏：窗口右下 (3840,2160)，截取尺寸 3840×2160，放大系数 2
        manager.set_screen_params(3840, 2160, 3840, 2160, coord_scale=2.0)
        self.assertEqual(manager._convert_coordinates(100, 50), (200, 100))

    def test_float_coordinates_use_physical_size(self):
        manager = KeyMouseManager()
        manager.set_screen_params(3840, 2160, 3840, 2160, coord_scale=2.0)
        # float 是距右/下边缘的比例，直接用物理尺寸换算
        self.assertEqual(manager._convert_coordinates(0.5, 0.5), (1920, 1080))

    def test_default_scale_keeps_base_behavior(self):
        manager = KeyMouseManager()
        manager.set_screen_params(1920, 1080, BASE_WIDTH, BASE_HEIGHT)
        self.assertEqual(manager._convert_coordinates(100, 50), (100, 50))
        self.assertEqual(manager._convert_coordinates(0.5, 0.5), (960, 540))

    def test_near_16_9_uses_independent_vertical_scale(self):
        manager = KeyMouseManager()
        manager.set_screen_params(3840, 2150, 3840, 2150,
                                  coord_scale=2.0, coord_scale_y=2150 / 1080)
        self.assertEqual(manager._convert_coordinates(100, 1080), (200, 2150))

    def test_capture_origin_controls_clicks(self):
        manager = KeyMouseManager()
        # 差分宇宙全屏截图保留的 9px 偏移也必须作用于管理器点击。
        manager.set_screen_params(3849, 2169, 3840, 2160, coord_scale=2.0)
        self.assertEqual(manager._convert_coordinates(100, 50), (209, 109))
        self.assertEqual(manager._convert_coordinates(0.5, 0.5), (1929, 1089))


class SoftTemplateMatchTests(unittest.TestCase):
    def test_soft_false_equals_plain_match(self):
        rng = np.random.default_rng(7)
        image = rng.integers(0, 255, (60, 80, 3), dtype=np.uint8)
        target = image[20:32, 30:43].copy()
        from tool.utils.image_tool import match_template_soft
        plain = cv2.matchTemplate(image, target, cv2.TM_CCORR_NORMED)
        np.testing.assert_array_equal(
            match_template_soft(image, target, False), plain
        )

    def test_soft_recovers_subpixel_shifted_content(self):
        # 构造亚像素平移 + 轻微软化的内容，模拟高分辨率截图缩放后的画质
        rng = np.random.default_rng(7)
        base = rng.integers(0, 255, (60, 80, 3), dtype=np.uint8)
        target = base[20:32, 30:43].copy()
        shifted = cv2.warpAffine(
            base, np.float32([[1, 0, 0.3], [0, 1, 0.4]]), (80, 60),
            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
        )
        image = cv2.GaussianBlur(shifted, (0, 0), 0.5)
        from tool.utils.image_tool import match_template_soft
        plain = cv2.minMaxLoc(cv2.matchTemplate(image, target, cv2.TM_CCORR_NORMED))[1]
        soft = cv2.minMaxLoc(match_template_soft(image, target, True))[1]
        self.assertGreater(soft, plain)
        self.assertGreater(soft, 0.98)

    def test_threshold_short_circuit_skips_compensation(self):
        rng = np.random.default_rng(7)
        image = rng.integers(0, 255, (60, 80, 3), dtype=np.uint8)
        target = image[20:32, 30:43].copy()
        shifted = cv2.warpAffine(
            image, np.float32([[1, 0, 0.3], [0, 1, 0.4]]), (80, 60),
            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
        )
        from tool.utils.image_tool import match_template_soft
        plain = cv2.matchTemplate(shifted, target, cv2.TM_CCORR_NORMED)
        peak = float(plain.max())
        # 明确达标：阈值低于峰值时直接返回原结果
        np.testing.assert_array_equal(
            match_template_soft(shifted, target, True, threshold=peak - 0.01), plain
        )
        # 明确失败：峰值远低于阈值时同样直接返回
        np.testing.assert_array_equal(
            match_template_soft(shifted, target, True, threshold=peak + 0.2), plain
        )


if __name__ == "__main__":
    unittest.main()
