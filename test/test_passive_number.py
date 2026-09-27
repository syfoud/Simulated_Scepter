"""真实 4K 重复数字与模板合成样本，验证被动百分比不会漏字。"""

import unittest
from pathlib import Path

import cv2
import numpy as np

from tool.utils.image_tool import (
    find_image_in_folder,
    load_all_images_from_directory,
    match_template_soft,
)
from tool.utils.ocr_num import extract_number, match_numbers_in_region

ROOT = Path(__file__).resolve().parents[1]


class PassiveNumberTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

    def test_recorded_4k_112_preserves_both_ones(self):
        crop = cv2.imread(str(ROOT / "test/fixtures/passive/bonus_112_4k.png"))
        self.assertIsNotNone(crop)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[691:1003, 80:195] = crop
        self.assertEqual(match_numbers_in_region(frame, soft=True), "+112%")

    def test_complete_template_numbers_at_both_scales(self):
        for value in ("0", "8", "24", "88", "104", "112", "160", "320"):
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            x = 82
            for char in f"+{value}%":
                template = find_image_in_folder("nums", char)
                height, width = template.shape[:2]
                frame[975:975 + height, x:x + width] = template
                x += width + 1
            for soft in (False, True):
                with self.subTest(value=value, soft=soft):
                    self.assertEqual(match_numbers_in_region(frame, soft=soft), f"+{value}%")

    def test_all_matches_compensates_a_weak_repeat_beside_a_strong_one(self):
        crop = cv2.imread(str(ROOT / "test/fixtures/passive/bonus_112_4k.png"))
        template = find_image_in_folder("nums", "1")
        single = match_template_soft(crop, template, True, cv2.TM_CCOEFF_NORMED, threshold=0.9)
        multiple = match_template_soft(
            crop, template, True, cv2.TM_CCOEFF_NORMED, threshold=0.9, all_matches=True,
        )
        self.assertGreater(single[284, 65], 0.9)
        self.assertLess(single[284, 52], 0.9)
        self.assertGreater(multiple[284, 52], 0.9)
        self.assertGreater(multiple[284, 65], 0.9)

    def test_blank_and_random_frames_have_no_passive_value(self):
        rng = np.random.default_rng(27)
        for frame in (np.zeros((1080, 1920, 3), dtype=np.uint8),
                      rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)):
            for soft in (False, True):
                with self.subTest(soft=soft):
                    self.assertIsNone(extract_number(match_numbers_in_region(frame, soft=soft)))


if __name__ == "__main__":
    unittest.main()
