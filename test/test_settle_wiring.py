"""结算动作脚本的接线测试：普通模拟宇宙与全仓动作脚本。

结算界面由标题「来自黑塔的分析报告」识别，命中后只调用内核的 settle_university：认不出标题
就不点，界面留在屏幕上下一轮重试，不再有第二条兜底点击路径把界面点掉。普通模拟宇宙的记账
也从「结束并结算」推迟到结算界面出现时，这样四个内核的结算都由同一处完成。

这里锁定：结算界面事件的识别文字与识别框、结算只用一个内核动作、结算界面排在点击空白类
事件之前（run_static 每轮只执行第一个命中事件）、「设置界面进行结算」只负责点按钮且不再
写状态（改用 interval 抑制连续命中）、以及全仓动作脚本里没有等已删除 end 状态的事件、
也没有 do_action 不认识的字典键。
"""
import json
import unittest
from pathlib import Path

from importing import load_img

# 内核在导入期就会读图像记忆切片，必须先预热图片缓存
load_img()

from core.simulated.engine import SimulatedUniverse  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASE_JSON = ROOT / "core" / "simulated" / "actions" / "universe.json"


# do_action 支持的字典动作（见 core/common/engine.py:114-143）：主键决定走哪个分支，
# 分支内部还会读几个附加键；除这些以外的键会被静默忽略。
ACTION_KEYS = {
    "text": {"text", "box", "redundancy"},
    "photo": {"photo", "threshold"},
    "position": {"position"},
    "sleep": {"sleep"},
    "real_sleep": {"real_sleep"},
    "press": {"press", "time"},
    "drag": {"drag"},
    "scroll": {"scroll"},
    "set_state": {"set_state"},
}
# 普通模拟宇宙里「点击空白处继续」的六类界面
BLANK_CLICK_EVENTS = (
    "获得祝福",
    "获得奇物",
    "获得物品",
    "失去祝福",
    "失去奇物",
    "失去物品",
)


def load_events(path):
    return json.loads(path.read_text(encoding="utf-8"))


def event_index(events, name):
    return next(i for i, event in enumerate(events) if event["name"] == name)


def core_action_files():
    return sorted((ROOT / "core").glob("*/actions/*.json"))


class BaseModeSettlementWiringTest(unittest.TestCase):
    """普通模拟宇宙的动作脚本：结算与「点击空白」细化事件共用一套界面识别。"""

    def setUp(self):
        self.events = load_events(BASE_JSON)

    def test_report_screen_settles_through_one_action(self):
        """结算界面一命中就做完记账、点掉界面、切分录像。"""
        event = self.events[0]

        self.assertEqual(event["name"], "结算界面")
        self.assertEqual(event["actions"], ["settle_university"])
        self.assertEqual(event["trigger"]["text"], "来自黑塔的分析报告")
        self.assertEqual(event["trigger"]["box"], [716, 1013, 217, 252])

    def test_report_screen_is_matched_before_the_blank_click_events(self):
        """run_static 每轮只执行第一个命中事件：结算界面必须排在点击空白类事件之前。"""
        names = [event["name"] for event in self.events]
        settle = names.index("结算界面")
        blank = [names.index(name) for name in BLANK_CLICK_EVENTS]

        self.assertLess(settle, min(blank))

    def test_settings_screen_only_clicks_the_confirm_button(self):
        """「结束并结算」只负责关界面，本局的记账推迟到结算界面出现时。"""
        event = self.events[event_index(self.events, "设置界面进行结算")]

        self.assertEqual(event["actions"], [{"position": [1393, 948]}])
        # 动作不再改变状态，靠 interval 抑制连续命中
        self.assertEqual(event["trigger"]["interval"], 1)

    def test_settlement_blank_event_is_gone(self):
        names = [event["name"] for event in self.events]

        self.assertNotIn("点击空白结算", names)

    def test_string_actions_are_kernel_methods(self):
        missing = {
            action
            for event in self.events
            for action in event["actions"]
            if isinstance(action, str) and not callable(getattr(SimulatedUniverse, action, None))
        }

        self.assertEqual(missing, set())


class ActionScriptSanityTest(unittest.TestCase):
    """全仓动作脚本的通用约束：不再等已删除的 end 状态，也不再用 do_action 不认识的键。"""

    def test_no_event_waits_for_the_deleted_end_state(self):
        offenders = [
            f"{path.name}:{event['name']}"
            for path in core_action_files()
            for event in load_events(path)
            if event["trigger"].get("condition") == "end"
        ]

        self.assertEqual(offenders, [])

    def test_dict_actions_only_use_keys_do_action_understands(self):
        """do_action 遇到不认识的键只是静默 return 0：写了 delay 这类键等于什么都没做。"""
        offenders = []
        for path in core_action_files():
            for event in load_events(path):
                for action in event["actions"]:
                    if not isinstance(action, dict):
                        continue
                    primary = [key for key in action if key in ACTION_KEYS]
                    allowed = ACTION_KEYS[primary[0]] if len(primary) == 1 else set()
                    unknown = set(action) - allowed
                    if unknown:
                        offenders.append(
                            f"{path.name}:{event['name']}:{sorted(unknown)}"
                        )

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
