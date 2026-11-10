"""开局奖励选择：一次整屏 OCR 后按固定优先级点击对应奖励文字。"""

import unittest
from unittest.mock import Mock, patch

import numpy as np

from importing import load_img

# 内核在导入期会读图像记忆切片，必须先预热图片缓存
load_img()

from core.any_fate.engine import AnyFateUniverse  # noqa: E402

# 开局奖励文字所在横条（与 select_start_bless 里传给 find_with_box 的值一致）
REWARD_BOX = [511, 477, 1409, 519]
# 选完奖励后的确认按钮（固定坐标）
CONFIRM_POINT = (948, 965)


class SelectStartBlessTest(unittest.TestCase):
    def setUp(self):
        self.manager = self.enterContext(patch("core.any_fate.engine.key_mouse_manager", Mock()))

    def engine(self, rows):
        engine = object.__new__(AnyFateUniverse)
        engine.ts = Mock()
        engine.ts.forward = Mock()
        engine.ts.find_with_box = Mock(return_value=rows)
        engine.get_screen = Mock(return_value=np.zeros((1080, 1920, 3), dtype=np.uint8))
        return engine

    def clicks(self):
        return [call.args for call in self.manager.click_point.call_args_list]

    def test_ocrs_exactly_once_and_clicks_preferred_reward(self):
        box = [600, 480, 900, 516]
        engine = self.engine([{"raw_text": "神奇宇宙", "box": box}])

        engine.select_start_bless()

        engine.ts.forward.assert_called_once_with(engine.get_screen.return_value)
        engine.ts.find_with_box.assert_called_once_with(box=REWARD_BOX, redundancy=30)
        self.assertEqual(
            self.clicks(),
            [((600 + 900) / 2, (480 + 516) / 2), CONFIRM_POINT],
        )

    def test_lower_priority_reward_is_clicked_when_higher_ones_are_absent(self):
        box = [950, 480, 1250, 516]
        engine = self.engine([{"raw_text": "巨胃宇宙", "box": box}])

        engine.select_start_bless()

        self.assertEqual(
            self.clicks(),
            [((950 + 1250) / 2, (480 + 516) / 2), CONFIRM_POINT],
        )

    def test_full_priority_order(self):
        priority = ("神奇宇宙", "巨胃宇宙", "破碎宇宙", "祝福宇宙")
        rows = [
            {"raw_text": name, "box": [600 + index * 100, 480, 800 + index * 100, 516]}
            for index, name in enumerate(reversed(priority))
        ]
        for index, expected in enumerate(priority):
            with self.subTest(expected=expected):
                # 每次留下当前最高优先级及更低优先级的奖励，验证选择顺序
                visible = [row for row in rows
                           if priority.index(row["raw_text"]) >= index]
                engine = self.engine(visible)
                self.manager.reset_mock()

                engine.select_start_bless()

                target = next(row for row in visible if row["raw_text"] == expected)
                box = target["box"]
                self.assertEqual(
                    self.clicks(),
                    [((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), CONFIRM_POINT],
                )

    def test_unknown_or_no_text_skips_without_blind_click(self):
        for rows in ([], [{"raw_text": "无关文本", "box": [600, 480, 900, 516]}]):
            with self.subTest(rows=rows):
                engine = self.engine(rows)
                self.manager.reset_mock()

                engine.select_start_bless()

                self.assertEqual(self.clicks(), [])
                engine.ts.forward.assert_called_once_with(engine.get_screen.return_value)


if __name__ == "__main__":
    unittest.main()
