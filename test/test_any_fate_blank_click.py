"""
「点击空白」细化触发器的接线测试。

背景：除结算界面（来自黑塔的分析报告）外，还有若干只要求「点击空白处继续/关闭」点掉的
界面。它们各自独立成事件，点击落点是同一个空白处：

- 获得/失去 祝福、奇物、物品：识别文字就是界面名；
- 进入位面2、初始效果、冒险介绍、挑战结束：识别文字取自该界面上唯一稳定的那行文字。

原先还有一个兜底的「点击空白」事件：run_static 每轮只执行第一个命中的事件，它一旦先命中，
细化事件就永远轮不到；该兜底事件在结算界面漏检时还会把界面点掉，跳过结算与录像切分，
因此已删除，改由这些事件逐个识别。

识别框必须框住整行识别结果（含图标名或前缀字）：find_with_box 要求识别框包含整行文字框，
只框住屏幕上肉眼所见的一部分会导致匹配失败。这些框都是按实机截图跑 OCR 校准过的。
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSECT_JSON = ROOT / "core" / "any_fate" / "actions" / "insect.json"
# 细化事件共用的点击落点
BLANK_CLICK = [1456, 875]
# 只在「点击空白处关闭/继续」时才需要点掉的独立界面：事件名 -> (识别文字, 识别框)
PLAIN_BLANK_EVENTS = {
    "进入位面2": ("位面", [905, 1015, 680, 725]),
    "初始效果": ("初始效果", [800, 1100, 494, 548]),
    "冒险介绍": ("挑战", [770, 935, 395, 437]),
    "挑战结束": ("挑战结束", [833, 1090, 321, 387]),
}
# 除结算界面之外的六类「点击空白处继续」界面
SPECIFIC_BLANK_EVENTS = (
    "获得祝福",
    "获得奇物",
    "获得物品",
    "失去祝福",
    "失去奇物",
    "失去物品",
)


def load_insect():
    return json.loads(INSECT_JSON.read_text(encoding="utf-8"))


def event_index(events, name):
    return next(i for i, event in enumerate(events) if event["name"] == name)


class SpecificBlankClickTest(unittest.TestCase):
    def test_specific_blank_events_match_their_own_text(self):
        """每个细化事件的识别文字与事件名一致，避免复制后忘记改文字。"""
        events = load_insect()

        for name in SPECIFIC_BLANK_EVENTS:
            with self.subTest(event=name):
                self.assertEqual(events[event_index(events, name)]["trigger"]["text"], name)

    def test_specific_blank_events_click_the_same_spot_as_the_plain_one(self):
        """六类细化事件只是识别文字不同，点击落点是同一个空白处。"""
        events = load_insect()

        for name in SPECIFIC_BLANK_EVENTS:
            with self.subTest(event=name):
                self.assertEqual(
                    events[event_index(events, name)]["actions"],
                    [{"position": BLANK_CLICK}],
                    f"{name} 的点击落点应与其它细化事件一致",
                )

    def test_specific_blank_events_are_grouped_after_entering_the_plane(self):
        """六类细化事件连续排在一起，紧跟「进入位面」之后。"""
        events = load_insect()
        start = event_index(events, "进入位面") + 1
        names = [event["name"] for event in events[start:start + len(SPECIFIC_BLANK_EVENTS)]]

        self.assertEqual(names, list(SPECIFIC_BLANK_EVENTS))


class PlainBlankClickTest(unittest.TestCase):
    def test_plain_blank_events_recognize_the_line_drawn_around_the_box(self):
        """识别文字与识别框要和实机截图校准出来的值一致，否则事件永远命不中。"""
        events = load_insect()

        for name, (text, box) in PLAIN_BLANK_EVENTS.items():
            with self.subTest(event=name):
                trigger = events[event_index(events, name)]["trigger"]

                self.assertEqual(trigger["text"], text)
                self.assertEqual(trigger["box"], box)

    def test_plain_blank_events_click_the_blank_spot(self):
        events = load_insect()

        for name in PLAIN_BLANK_EVENTS:
            with self.subTest(event=name):
                self.assertEqual(
                    events[event_index(events, name)]["actions"],
                    [{"position": BLANK_CLICK}],
                    f"{name} 的点击落点应与其它点击空白事件一致",
                )


if __name__ == "__main__":
    unittest.main()
