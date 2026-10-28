"""
结算界面（来自黑塔的分析报告）的接线测试。

背景：结算界面里标题与下方的「点击空白处继续」同时存在，动画里标题比「点击空白处继续」
早出现约一到两帧（录屏实测），而界面接受点击还要再晚约 0.3~0.5 秒，所以首次识别到标题时的
那一次点击有概率不生效。因此结算只由「结算界面」这一个事件负责、整段结算交给内核的
settle_university 一个动作：认不出标题就不点，界面留在屏幕上，下一轮重新识别；点不掉界面时
下一轮再命中只会补一次点击，不会重复记账（见 test_settle_university.py 对闸门的测试）。

这里锁定 insect.json 的接线：结算界面识别的文字与识别框、结算只用一个内核动作、不再有
独立的「点击空白结算」和兜底的「点击空白」事件（避免漏检时有另一条点击路径把界面点掉）、
「结束并结算」连点结算按钮与确认框、以及脚本动作都能在内核上找到同名方法。
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
# 「结束并结算」后连点的两处：结算按钮、随后弹出的确认框
CONFIRM_CLICKS = [{"position": [1393, 948]}, {"position": [1147, 676]}]


def load_insect():
    return json.loads(INSECT_JSON.read_text(encoding="utf-8"))


def event_index(events, name):
    return next(i for i, event in enumerate(events) if event["name"] == name)


class SettlementJsonTest(unittest.TestCase):
    """锁定 insect.json 里结算相关的接线，脚本里删事件、改动作顺序都会在这里报错。"""

    def test_settlement_event_settles_through_one_kernel_action(self):
        """「结算界面」一次做完记账、点掉界面、切分录像，不再依赖下一轮的「点击空白结算」。"""
        events = load_insect()

        event = events[event_index(events, "结算界面")]

        self.assertEqual(event["actions"], ["settle_university"])

    def test_settlement_event_matches_the_report_title(self):
        """结算界面靠标题文字识别，识别文字与识别框必须与实测画面一致。"""
        events = load_insect()

        trigger = events[event_index(events, "结算界面")]["trigger"]

        self.assertEqual(trigger["text"], REPORT_TITLE)
        self.assertEqual(trigger["box"], TITLE_BOX)

    def test_settings_screen_clicks_button_and_confirmation(self):
        """「结束并结算」要连点结算按钮与确认框，只点第一处会停在确认框上。"""
        events = load_insect()

        event = events[event_index(events, "设置界面进行结算")]

        self.assertEqual(event["actions"], CONFIRM_CLICKS)
        self.assertEqual(event["trigger"]["condition"], "exit")

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
