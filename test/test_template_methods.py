"""通过三个实际工具类验证 4K 模板补偿、阈值与有界点击等待。"""

import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tool.utils.image_tool import load_all_images_from_directory, match_template_soft

load_all_images_from_directory()

import tool.currency.utils as currency_utils
import tool.diver.utils as diver_utils
import tool.simul.utils as simul_utils

MODES = (
    (simul_utils, simul_utils.UniverseUtils),
    (currency_utils, currency_utils.CurrencyUtils),
    (diver_utils, diver_utils.UniverseUtils),
)


class TemplateMethodTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        base = rng.integers(0, 255, (60, 80, 3), dtype=np.uint8)
        self.target = base[20:32, 30:43].copy()
        shifted = cv2.warpAffine(
            base, np.float32([[1, 0, 0.3], [0, 1, 0.4]]), (80, 60),
            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
        )
        self.frame = cv2.GaussianBlur(shifted, (0, 0), 0.5)

    def make_utils(self, cls, scale=2.0):
        utils = object.__new__(cls)
        utils.cap_scale = scale
        utils.scx = 1.0
        utils.xx, utils.yy = 1920, 1080
        utils.threshold = 0.98
        utils.last_info = None
        utils._stop = False
        utils.get_local = Mock(return_value=self.frame)
        utils.get_screen = Mock(return_value=self.frame)
        return utils

    def test_check_compensates_4k_without_changing_1080p_threshold(self):
        for module, cls in MODES:
            loader = "cv.imread" if module is diver_utils else "find_image_by_name"
            for scale, expected in ((1.0, False), (2.0, True)):
                with self.subTest(mode=module.__name__, scale=scale):
                    utils = self.make_utils(cls, scale)
                    with patch(f"{module.__name__}.{loader}", return_value=self.target):
                        self.assertEqual(utils.check("sample", 0.5, 0.5, threshold=0.98), expected)
                    self.assertGreater(utils.tm, 0.98) if expected else self.assertLess(utils.tm, 0.98)

    def test_strict_threshold_is_not_lowered_for_4k(self):
        for module, cls in MODES:
            loader = "cv.imread" if module is diver_utils else "find_image_by_name"
            utils = self.make_utils(cls)
            with self.subTest(mode=module.__name__), patch(
                f"{module.__name__}.{loader}", return_value=self.target
            ), patch(f"{module.__name__}.match_template_soft", return_value=np.array([[0.96]], dtype=np.float32)) as matcher:
                self.assertFalse(utils.check("sample", 0.5, 0.5, threshold=0.98))
            self.assertEqual(matcher.call_args.kwargs["threshold"], 0.98)

    def test_scan_uses_game_frame_and_capture_scale_with_existing_metric(self):
        for module, cls in MODES:
            for scale in (1.0, 2.0):
                utils = self.make_utils(cls, scale)
                with self.subTest(mode=module.__name__, scale=scale), patch(
                    f"{module.__name__}.match_template_soft", wraps=match_template_soft
                ) as matcher:
                    result = utils.scan_screenshot(self.target, threshold=0.98)
                self.assertIs(result["screenshot"], self.frame)
                utils.get_screen.assert_called_once_with()
                self.assertEqual(matcher.call_args.args[2:4], (scale != 1.0, cv2.TM_CCOEFF_NORMED))
                self.assertEqual(matcher.call_args.kwargs["threshold"], 0.98)

    def test_diver_mask_and_binary_matching_preserve_original_paths(self):
        mask = np.full(self.target.shape[:2], 255, dtype=np.uint8)
        mask[:, :3] = 0
        for binary in (False, True):
            utils = self.make_utils(diver_utils.UniverseUtils)
            with self.subTest(binary=binary), patch(
                "tool.diver.utils.match_template_soft"
            ) as soft, patch("tool.diver.utils.cv.matchTemplate", wraps=cv2.matchTemplate) as matcher:
                result = utils.scan_screenshot(self.target, mask=mask, use_binary=binary, threshold=0.98)
            soft.assert_not_called()
            self.assertIs(matcher.call_args.kwargs["mask"], mask)
            self.assertIs(result["screenshot"], self.frame)

    def test_simul_and_currency_waits_stop_at_timeout_without_clicking(self):
        for module, cls in MODES[:2]:
            utils = self.make_utils(cls)
            utils.scan_screenshot = Mock(return_value={"max_val": 0.5})
            times = iter([0.0, 1.0, 5.0, 9.9, 10.0])
            with self.subTest(mode=module.__name__), patch(
                f"{module.__name__}.time.monotonic", side_effect=lambda: next(times, 1e9)
            ), patch(f"{module.__name__}.time.sleep"), patch(f"{module.__name__}.key_mouse_manager") as manager:
                self.assertFalse(utils.click_target(self.target, 0.9, click=True))
            manager.click.assert_not_called()
            self.assertEqual(utils.scan_screenshot.call_count, 4)
            self.assertGreaterEqual(utils.scan_screenshot.call_args.args[1], 0.85)

    def test_simul_and_currency_stop_after_scan_does_not_click(self):
        for module, cls in MODES[:2]:
            utils = self.make_utils(cls)

            def stop_after_scan(*args):
                utils._stop = True
                return {"max_val": 0.99}

            utils.scan_screenshot = Mock(side_effect=stop_after_scan)
            with self.subTest(mode=module.__name__), patch(f"{module.__name__}.key_mouse_manager") as manager:
                self.assertFalse(utils.click_target(self.target, 0.9, click=True))
            manager.click.assert_not_called()
            utils.scan_screenshot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
