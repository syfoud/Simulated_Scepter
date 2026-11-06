"""开局奖励选择：复用整屏 OCR 的文本框定位目标，不在固定中点盲点。"""

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
# 两个目标都没认到时的兜底点击点
FALLBACK_POINT = (960, 540)


class SelectStartBlessTest(unittest.TestCase):
    def setUp(self):
        self.manager = self.enterContext(patch("core.any_fate.engine.key_mouse_manager", Mock()))

    def engine(self, rows, cached_res=True):
        engine = object.__new__(AnyFateUniverse)
        engine.ts = Mock()
        engine.ts.res = [1] if cached_res else []
        engine.ts.forward = Mock()
        engine.ts.find_with_box = Mock(return_value=rows)
        engine.get_screen = Mock(return_value=np.zeros((1080, 1920, 3), dtype=np.uint8))
        return engine

    def clicks(self):
        return [call.args for call in self.manager.click_point.call_args_list]

    def test_target_reward_is_clicked_at_its_text_center(self):
        box = [600, 480, 900, 516]
        engine = self.engine([{"raw_text": "神奇宇宙", "box": box}])

        engine.select_start_bless()

        self.assertEqual(
            self.clicks(),
            [((600 + 900) / 2, (480 + 516) / 2), CONFIRM_POINT],
        )
        engine.ts.find_with_box.assert_called_with(box=REWARD_BOX, redundancy=30)

    def test_giant_stomach_reward_is_also_matched(self):
        box = [950, 480, 1250, 516]
        engine = self.engine([{"raw_text": "巨胃宇宙", "box": box}])

        engine.select_start_bless()

        self.assertEqual(
            self.clicks(),
            [((950 + 1250) / 2, (480 + 516) / 2), CONFIRM_POINT],
        )

    def test_cached_ocr_result_is_reused_without_a_new_screen_ocr(self):
        engine = self.engine([{"raw_text": "神奇宇宙", "box": [600, 480, 900, 516]}])

        engine.select_start_bless()

        engine.ts.forward.assert_not_called()

    def test_missing_cache_triggers_one_whole_screen_ocr(self):
        engine = self.engine([], cached_res=False)

        engine.select_start_bless()

        engine.ts.forward.assert_called_once_with(engine.get_screen.return_value)

    def test_no_target_falls_back_to_the_middle_of_the_screen(self):
        engine = self.engine([{"raw_text": "无关文本", "box": [600, 480, 900, 516]}])

        engine.select_start_bless()

        self.assertEqual(self.clicks(), [FALLBACK_POINT, CONFIRM_POINT])


if __name__ == "__main__":
    unittest.main()
