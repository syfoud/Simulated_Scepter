"""货币战争人数裁片的边界回归：斜杠切分失败时不能把空图交给 OCR。"""

import unittest
from unittest.mock import Mock

import numpy as np

from core.currency import automation
from core.currency.automation import read_count_number, split_count_line


class TeamCountCropTest(unittest.TestCase):
    def test_read_count_number_ignores_empty_patch(self):
        recognizer = Mock()
        for patch in (np.zeros((0, 10, 3), dtype=np.uint8), np.zeros((10, 0, 3), dtype=np.uint8)):
            with self.subTest(shape=patch.shape):
                self.assertIsNone(read_count_number(recognizer, patch))
        recognizer.ocr_one_row.assert_not_called()

    def split_with_mask(self, patch, mask):
        original = automation.count_mask
        automation.count_mask = Mock(return_value=mask)
        try:
            return split_count_line(patch)
        finally:
            automation.count_mask = original

    def test_split_count_line_never_returns_empty_half(self):
        # 用一条贴着左边缘的斜线模拟误识别：旧实现会返回空的左半段
        mask = np.zeros((20, 30), dtype=bool)
        for index in range(20):
            mask[index, index] = True
        patch = np.zeros((20, 30, 3), dtype=np.uint8)

        self.assertIsNone(self.split_with_mask(patch, mask))

    def test_split_count_line_requires_both_halves_to_have_pixels(self):
        mask = np.zeros((20, 40), dtype=bool)
        for index in range(20):
            mask[index, 10 + index] = True
        patch = np.zeros((20, 40, 3), dtype=np.uint8)

        halves = self.split_with_mask(patch, mask)

        self.assertIsNotNone(halves)
        left, right = halves
        self.assertGreater(left.size, 0)
        self.assertGreater(right.size, 0)


if __name__ == "__main__":
    unittest.main()
