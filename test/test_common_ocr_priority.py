"""OCR 文本查找：列表模式的优先级只看列表顺序，与 OCR 返回顺序无关。"""

import unittest
from unittest.mock import Mock

import numpy as np

from core.common.ocr import My_TS


def box(x, y):
    return np.array([[x, y], [x + 40, y], [x + 40, y + 20], [x, y + 20]])


class FindTextPriorityTest(unittest.TestCase):
    def engine(self, results):
        ts = My_TS.__new__(My_TS)
        ts._ts = Mock()
        ts._ts.ocr = Mock(return_value=results)
        ts.text = ""
        ts.nothing = 1
        return ts

    def test_list_mode_returns_the_highest_priority_match(self):
        # OCR 先返回低优先文本，再返回高优先文本：列表模式下仍要选高优先的
        engine = self.engine([
            (box(10, 10), ("普通选项", 0.99)),
            (box(50, 50), ("优选项", 0.95)),
        ])

        result = engine.find_text(np.zeros((1080, 1920, 3), dtype=np.uint8), ["优选项", "普通选项"])

        self.assertTrue(np.array_equal(result, box(50, 50)))

    def test_scan_order_is_irrelevant(self):
        for results in (
            [(box(10, 10), ("普通选项", 0.99)), (box(50, 50), ("优选项", 0.95))],
            [(box(50, 50), ("优选项", 0.95)), (box(10, 10), ("普通选项", 0.99))],
        ):
            with self.subTest(order=[item[1][0] for item in results]):
                engine = self.engine(results)
                result = engine.find_text(
                    np.zeros((1080, 1920, 3), dtype=np.uint8), ["优选项", "普通选项"]
                )
                self.assertTrue(np.array_equal(result, box(50, 50)))

    def test_missing_high_priority_text_falls_back_to_lower_priority(self):
        engine = self.engine([(box(10, 10), ("普通选项", 0.99))])

        result = engine.find_text(np.zeros((1080, 1920, 3), dtype=np.uint8), ["优选项", "普通选项"])

        self.assertTrue(np.array_equal(result, box(10, 10)))

    def test_single_text_mode_still_returns_first_hit(self):
        engine = self.engine([
            (box(10, 10), ("普通选项", 0.99)),
            (box(50, 50), ("普通选项", 0.95)),
        ])

        result = engine.find_text(np.zeros((1080, 1920, 3), dtype=np.uint8), "普通选项")

        self.assertTrue(np.array_equal(result, box(10, 10)))

    def test_no_match_returns_none(self):
        engine = self.engine([(box(10, 10), ("普通选项", 0.99))])

        self.assertIsNone(
            engine.find_text(np.zeros((1080, 1920, 3), dtype=np.uint8), ["不存在"])
        )


if __name__ == "__main__":
    unittest.main()
