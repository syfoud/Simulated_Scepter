"""校验队伍空槽位的模板匹配（合成图，不依赖实机截图）。"""

import unittest

import numpy as np

from divine_treasure_entry import TEAM_EMPTY_SLOT_BOX, match_in_box


def noisy_template(seed=0, height=14, width=27):
    """用噪声当模板：纯色模板在纯色背景上算 CCOEFF 会不稳定。"""
    return np.random.default_rng(seed).integers(0, 255, (height, width, 3), dtype=np.uint8)


class TestMatchInBox(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((1080, 1920, 3), np.uint8)
        self.template = noisy_template()
        x1, x2, y1, y2 = TEAM_EMPTY_SLOT_BOX
        # 把模板贴进搜索区的左上角，中心应落在 (x1 + 13, y1 + 7)
        self.image[y1:y1 + 14, x1:x1 + 27] = self.template

    def test_hits_inside_region(self):
        result = match_in_box(self.image, self.template, TEAM_EMPTY_SLOT_BOX, threshold=0.9)
        self.assertIsNotNone(result)
        score, (x, y) = result
        self.assertGreater(score, 0.99)
        x1, _, y1, _ = TEAM_EMPTY_SLOT_BOX
        self.assertEqual((x, y), (x1 + 13, y1 + 7))

    def test_outside_region_is_ignored(self):
        blank = np.zeros_like(self.image)
        x1, x2, y1, y2 = TEAM_EMPTY_SLOT_BOX
        blank[100:114, 100:127] = self.template  # 贴在搜索区外面
        self.assertIsNone(match_in_box(blank, self.template, TEAM_EMPTY_SLOT_BOX, threshold=0.9))

    def test_blank_region_returns_none(self):
        blank = np.zeros_like(self.image)
        self.assertIsNone(match_in_box(blank, self.template, TEAM_EMPTY_SLOT_BOX, threshold=0.9))

    def test_missing_template_returns_none(self):
        self.assertIsNone(match_in_box(self.image, None, TEAM_EMPTY_SLOT_BOX))


if __name__ == "__main__":
    unittest.main()
