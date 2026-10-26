"""
模拟宇宙结算界面「来自黑塔的分析报告」漏检的兜底回归测试。

背景：结算界面（来自黑塔的分析报告）里，标题与下方的「点击空白处继续」同时存在，
动画里标题比「点击空白处继续」早出现约一到两帧（录屏实测），两者都渲染完之后整屏 OCR
能稳定认出标题。但整屏 OCR 仍有极小概率漏掉标题，此时界面会被普通的「点击空白」点掉，
本局的 end_of_university() 与 restart_recording() 都被跳过：轮次不计数、录像不切分，
状态也不会走到 end。

现在的行为（core/any_fate/engine.py 的 click_blank，由 insect.json「点击空白」触发）：
真正点掉界面之前，只识别一次标题所在的那一行（ocr_one_row，几十毫秒），命中就补齐结算的
全部动作——end_of_university、点掉界面、restart_recording——本轮不再走普通点击。
state 为 end / re_start 表示本局刚结算过、界面可能还没消失，此时不再重复结算。
「结算界面」事件保留在 insect.json 的第一位，作为整屏 OCR 认得到标题时的正常入口。
"""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

# 内核在导入期就会读图像记忆切片（例如 tool/utils/predict.py），需要先装载图像缓存
ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.engine import AnyFateUniverse

INSECT_JSON = ROOT / "core" / "any_fate" / "actions" / "insect.json"
# 结算界面标题与它的识别框（与 click_blank、insect.json「结算界面」同值：改实现时这里要跟着改）
REPORT_TITLE = "来自黑塔的分析报告"
TITLE_BOX = [716, 1013, 217, 252]
# 结算界面上的点击落点（insect.json「结算界面」与 click_blank 补做结算时同值）
SETTLE_CLICK = [900, 1000]
# 普通「点击空白」的兜底点击落点
BLANK_CLICK = [1456, 875]
# 只有结算界面存在时才会进入的两个状态
SETTLED_STATES = ("end", "re_start")
SCREEN = np.zeros((1080, 1920, 3), dtype=np.uint8)


def make_engine(state="run", title=""):
    """只提供 click_blank() 所需接口的替身：结算动作与 OCR 全部打桩。"""
    engine = AnyFateUniverse.__new__(AnyFateUniverse)
    engine.state = state
    engine.screen = SCREEN
    engine.get_screen = Mock(return_value=SCREEN)
    engine.ts = Mock()
    engine.ts.ocr_one_row = Mock(return_value=title)
    engine.end_of_university = Mock()
    engine.click_position = Mock()
    engine.restart_recording = Mock()
    return engine


def load_insect():
    return json.loads(INSECT_JSON.read_text(encoding="utf-8"))


def event_index(events, name):
    return next(i for i, event in enumerate(events) if event["name"] == name)


class ClickBlankTest(unittest.TestCase):
    def setUp(self):
        self.logger = Mock()
        self.enterContext(patch("core.any_fate.engine.CUS_LOGGER", self.logger))

    def test_missed_settlement_is_completed_before_the_blank_click(self):
        """整屏漏检标题时，补检命中就补齐结算：结算、点掉界面、切分录像，一次做完。"""
        engine = make_engine(state="run", title=REPORT_TITLE)

        engine.click_blank()

        engine.end_of_university.assert_called_once_with()
        self.assertEqual([c.args for c in engine.click_position.call_args_list], [(SETTLE_CLICK,)])
        engine.restart_recording.assert_called_once_with()
        self.assertTrue(
            any("补做结算" in c.args[0] for c in self.logger.warning.call_args_list),
            self.logger.warning.call_args_list,
        )

    def test_title_is_read_from_the_same_line_as_the_settlement_trigger(self):
        """补检只识别标题那一行，识别框与 insect.json「结算界面」的触发框一致。"""
        engine = make_engine(title="")

        engine.click_blank()

        self.assertEqual(engine.ts.ocr_one_row.call_args.kwargs["box"], TITLE_BOX)
        trigger_box = next(
            event["trigger"]["box"]
            for event in load_insect()
            if event["name"] == "结算界面"
        )
        self.assertEqual(TITLE_BOX, trigger_box)

    def test_title_not_recognized_falls_back_to_the_plain_click(self):
        """补检也没认出标题（真的不是结算界面）：照旧点空白处，不结算、不切分录像。"""
        engine = make_engine(state="run", title="")

        engine.click_blank()

        self.assertEqual([c.args for c in engine.click_position.call_args_list], [(BLANK_CLICK,)])
        engine.end_of_university.assert_not_called()
        engine.restart_recording.assert_not_called()
        self.assertEqual(self.logger.warning.call_args_list, [])

    def test_ocr_noise_around_the_title_still_settles(self):
        """OCR 前后可能带出标点或别行文字：按包含判断而不是相等。"""
        engine = make_engine(title="| 来自黑塔的分析报告 。")

        engine.click_blank()

        engine.end_of_university.assert_called_once_with()
        engine.restart_recording.assert_called_once_with()

    def test_already_settled_states_skip_the_extra_ocr(self):
        """刚结算过（end / re_start，界面正在消失）时不再补检标题，也不再结算一次。"""
        for state in SETTLED_STATES:
            with self.subTest(state=state):
                engine = make_engine(state=state, title=REPORT_TITLE)

                engine.click_blank()

                engine.ts.ocr_one_row.assert_not_called()
                engine.end_of_university.assert_not_called()
                engine.restart_recording.assert_not_called()
                self.assertEqual(
                    [c.args for c in engine.click_position.call_args_list], [(BLANK_CLICK,)]
                )


class SettlementJsonTest(unittest.TestCase):
    """insect.json 的结算接线：脚本删掉的事件、动作顺序与判定优先级都在这里锁住。"""

    def test_settlement_event_settles_clicks_and_restarts_in_one_iteration(self):
        """「结算界面」一次做完结算、点掉界面、切分录像，不再依赖下一轮的「点击空白结算」。"""
        events = load_insect()
        event = events[event_index(events, "结算界面")]

        self.assertEqual(
            event["actions"],
            ["end_of_university", {"position": SETTLE_CLICK}, "restart_recording"],
        )

    def test_plain_blank_click_goes_through_click_blank(self):
        """普通「点击空白」的动作是 click_blank：点掉界面之前补检一次标题。"""
        events = load_insect()
        event = events[event_index(events, "点击空白")]

        self.assertEqual(event["actions"], ["click_blank"])

    def test_the_separate_settlement_blank_event_is_gone(self):
        """「点击空白结算」已删除：结算界面的点击由「结算界面」自己完成，避免漏检时两套点击并存。"""
        names = [event["name"] for event in load_insect()]

        self.assertNotIn("点击空白结算", names)

    def test_settlement_is_checked_before_the_plain_blank(self):
        """「结算界面」必须排在普通「点击空白」之前：run_static 只执行第一个命中的事件。"""
        events = load_insect()

        self.assertLess(event_index(events, "结算界面"), event_index(events, "点击空白"))

    def test_every_script_action_is_a_kernel_method(self):
        """脚本里的每个字符串动作都要能在内核上找到同名方法（do_action 直接 getattr 调用）。"""
        missing = {
            action
            for event in load_insect()
            for action in event["actions"]
            if isinstance(action, str) and not callable(getattr(AnyFateUniverse, action, None))
        }

        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
