"""
结算界面（来自黑塔的分析报告）的接线测试。

背景：结算界面里标题与下方的「点击空白处继续」同时存在，动画里标题比「点击空白处继续」
早出现约一到两帧（录屏实测），两者都渲染完成之后整屏 OCR 能稳定认出标题。因此结算只由
「结算界面」这一个事件负责：认出标题就一次做完结算、点掉界面、切分录像；没认出来就不点，
界面留在屏幕上，下一轮重新识别，比让别的「点击空白」事件把界面点掉更安全。

这里锁定 insect.json 的接线：结算界面识别的文字与识别框、结算动作与点击落点、不再有
独立的「点击空白结算」和兜底的「点击空白」事件（避免漏检时有另一条点击路径把界面点掉）、
以及脚本动作都能在内核上找到同名方法。
"""

import json
import unittest
from pathlib import Path

from tool.utils.image_tool import load_all_images_from_directory

ROOT = Path(__file__).resolve().parents[1]
# 内核在导入期就会读图像记忆切片（例如 tool/utils/predict.py），需要先装载图像缓存
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.engine import AnyFateUniverse  # noqa: E402

INSECT_JSON = ROOT / "core" / "any_fate" / "actions" / "insect.json"

REPORT_TITLE = "来自黑塔的分析报告"
# 结算界面标题的识别框（与 insect.json「结算界面」同值：改实现时这里要跟着改）
TITLE_BOX = [716, 1013, 217, 252]
# 结算界面上的点击落点（与 insect.json「结算界面」同值）
SETTLE_CLICK = [900, 1000]


def load_insect():
    return json.loads(INSECT_JSON.read_text(encoding="utf-8"))


def event_index(events, name):
    return next(i for i, event in enumerate(events) if event["name"] == name)


class SettlementJsonTest(unittest.TestCase):
    """锁定 insect.json 里结算相关的接线，脚本里删事件、改动作顺序都会在这里报错。"""

    def test_settlement_event_settles_clicks_and_restarts_in_one_iteration(self):
        """「结算界面」一次做完结算、点掉界面、切分录像，不再依赖下一轮的「点击空白结算」。"""
        events = load_insect()

        event = events[event_index(events, "结算界面")]

        self.assertEqual(
            event["actions"],
            ["end_of_university", {"position": SETTLE_CLICK}, "restart_recording"],
        )

    def test_settlement_event_matches_the_report_title(self):
        """结算界面靠标题文字识别，识别文字与识别框必须与实测画面一致。"""
        events = load_insect()

        trigger = events[event_index(events, "结算界面")]["trigger"]

        self.assertEqual(trigger["text"], REPORT_TITLE)
        self.assertEqual(trigger["box"], TITLE_BOX)

    def test_the_separate_settlement_blank_event_is_gone(self):
        """「点击空白结算」已删除：结算界面的点击由「结算界面」自己完成，避免漏检时两套点击并存。"""
        names = [event["name"] for event in load_insect()]

        self.assertNotIn("点击空白结算", names)

    def test_the_plain_blank_event_is_gone(self):
        """兜底的「点击空白」已删除：它会在结算界面漏检时把界面点掉，跳过结算与录像切分。"""
        names = [event["name"] for event in load_insect()]

        self.assertNotIn("点击空白", names)

    def test_every_script_action_is_a_kernel_method(self):
        """脚本里的字符串动作由 do_action 直接 getattr 调用，必须都是内核上的方法。"""
        missing = {
            action
            for event in load_insect()
            for action in event["actions"]
            if isinstance(action, str) and not callable(getattr(AnyFateUniverse, action, None))
        }

        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
