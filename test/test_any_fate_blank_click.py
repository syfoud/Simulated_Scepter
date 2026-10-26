"""
「点击空白」细化触发器的接线测试。

背景：除结算界面（来自黑塔的分析报告）外，还有若干只要求「点击空白处继续」点掉的界面
（获得祝福、获得奇物、获得物品、失去祝福、失去奇物、失去物品）。它们原本都由兜底的
「点击空白」处理，但 run_static 每轮只执行第一个命中的事件，兜底事件一旦先命中，细化
事件就永远轮不到，所以六类界面各自独立成事件；点击落点与兜底一致，只是优先匹配。
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSECT_JSON = ROOT / "core" / "any_fate" / "actions" / "insect.json"
# 兜底点击的落点（六类细化事件与「点击空白」同值）
BLANK_CLICK = [1456, 875]
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
        """细化事件只是优先匹配，点击落点与兜底「点击空白」一致。"""
        events = load_insect()

        for name in SPECIFIC_BLANK_EVENTS:
            with self.subTest(event=name):
                self.assertEqual(
                    events[event_index(events, name)]["actions"],
                    [{"position": BLANK_CLICK}],
                    f"{name} 的点击落点应与兜底「点击空白」一致",
                )

    def test_specific_blank_events_are_grouped_after_entering_the_plane(self):
        """六类细化事件连续排在一起，紧跟「进入位面」之后。"""
        events = load_insect()
        start = event_index(events, "进入位面") + 1
        names = [event["name"] for event in events[start:start + len(SPECIFIC_BLANK_EVENTS)]]

        self.assertEqual(names, list(SPECIFIC_BLANK_EVENTS))


if __name__ == "__main__":
    unittest.main()
