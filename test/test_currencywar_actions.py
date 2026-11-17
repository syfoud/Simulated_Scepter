import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.common.engine import StateKernel
from core.currency.automation import SimulatedCurrency
from core.currency.run_history import RUN_END_ACTION


class CurrencyWarActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config_path = Path(__file__).resolve().parents[1] / "core" / "currency" / "actions" / "currencywar.json"
        with config_path.open(encoding="utf-8") as config_file:
            cls.actions = json.load(config_file)

    def test_chalice_trial_popup_selects_left_trial_and_confirms(self):
        matches = [
            action
            for action in self.actions
            if action.get("name") == "命运圣杯祈愿试炼"
        ]

        self.assertEqual(len(matches), 1)
        self.assertEqual(
            matches[0],
            {
                "name": "命运圣杯祈愿试炼",
                "trigger": {
                    "text": "请选择一个祈愿试炼",
                    "box": [1400, 572, 1595, 599],
                    "interval": 2,
                    "redundancy": 30,
                    "once": True,
                },
                "actions": [
                    {"position": [684, 398]},
                    {"sleep": 0.5},
                    {"position": [1495, 639]},
                ],
            },
        )

    def test_popup_and_exit_events_trigger_once(self):
        once_names = {
            action["name"]
            for action in self.actions
            if action["trigger"].get("once")
        }

        self.assertEqual(
            once_names,
            # 「啊哈大悦」不在这里：它去掉 once 了，点不掉时下一轮还要能重点
            {"盛会之星", "领航员", "命运圣杯祈愿试炼", "独家代言", "开始退出"},
        )

    def test_item_detail_confirms_selection_before_escape(self):
        names = [action.get("name") for action in self.actions]
        confirm = next(
            action
            for action in self.actions
            if action.get("name") == "物品详情确认选择"
        )
        detail = next(
            action
            for action in self.actions
            if action.get("name") == "物品详情弹层"
        )

        self.assertEqual(confirm["trigger"]["text"], "确认选择")
        self.assertEqual(
            confirm["actions"],
            [{"text": "确认选择", "box": [700, 880, 1250, 1050]}],
        )
        self.assertEqual(detail["trigger"]["text"], "装备")
        self.assertEqual(detail["actions"], [{"press": "esc"}])
        self.assertLess(names.index("物品详情确认选择"), names.index("物品详情弹层"))

    def test_every_string_action_exists_on_kernel(self):
        """JSON 里写成字符串的动作必须真能在内核上找到同名方法，别写错名字。"""
        missing = []
        for action in self.actions:
            for step in action["actions"]:
                if isinstance(step, str) and not callable(
                        getattr(SimulatedCurrency, step, None)):
                    missing.append(f"{action['name']} -> {step}")
        self.assertEqual(missing, [])

    def test_run_end_action_keeps_expected_name(self):
        action_names = {action.get("name") for action in self.actions}

        self.assertIn(RUN_END_ACTION, action_names)

    def test_blank_prompt_is_one_action_covering_all_screens(self):
        """三处「点击空白处继续」合成一条，靠宽条带罩住，点的是识别到的那块文字。"""
        actions = [a for a in self.actions if a.get("name") == "点击空白继续"]
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["trigger"]["text"], "点击空白处继续")
        self.assertEqual(action["actions"], ["click_blank_prompt"])
        left, top, right, bottom = action["trigger"]["box"]
        for band in ((689, 718), (778, 807), (948, 975)):   # 奇遇 / 首领 / 初始
            self.assertLessEqual(top, band[0])
            self.assertGreaterEqual(bottom, band[1])

    def test_start_button_checks_difficulty_before_starting_run(self):
        matches = [
            action
            for action in self.actions
            if action["trigger"].get("text") == "开始对局"
        ]

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["actions"], ["handle_difficulty_selection"])

    def test_environment_state_advances_only_inside_selection_action(self):
        action = next(
            action
            for action in self.actions
            if action.get("name") == "选择投资环境"
        )

        self.assertEqual(action["actions"], ["select_envir"])

    def test_battle_requires_ready_and_preparation_can_resume_current_screen(self):
        by_name = {action["name"]: action for action in self.actions}
        self.assertEqual(by_name["出战"]["trigger"]["condition"], "battle_ready")
        self.assertTrue(by_name["出战"]["trigger"]["state_only"])
        self.assertEqual(by_name["出战"]["actions"], ["start_battle"])
        self.assertNotIn("condition", by_name["出战前准备"]["trigger"])
        self.assertEqual(by_name["出战前准备"]["actions"], ["prepare_battle"])
        self.assertEqual(by_name["1-1主界面进战"]["trigger"]["condition"], "1-1")
        self.assertEqual(by_name["出战人数"]["trigger"]["condition"], "startbattle")

    def test_peace_token_skip_action_handles_both_remaining_counts(self):
        skip_action = next(
            action for action in self.actions if action.get("name") == "跳过战斗"
        )
        battle_index = next(
            index
            for index, action in enumerate(self.actions)
            if action.get("name") == "出战"
        )
        skip_index = self.actions.index(skip_action)

        self.assertLess(skip_index, battle_index)
        self.assertEqual(skip_action["trigger"]["text"], "跳过")
        # 拿到免战牌后状态可能还停在 startbattle，不能带状态门槛，否则永远不触发
        self.assertNotIn("condition", skip_action["trigger"])
        self.assertEqual(skip_action["trigger"]["box"], [1600, 700, 1920, 790])
        self.assertEqual(skip_action["actions"], [{"position": [1818, 750]}])
        self.assertIn(skip_action["trigger"]["text"], "跳过(2/2)")
        self.assertIn(skip_action["trigger"]["text"], "跳过(1/2)")

    def test_run_static_executes_peace_token_skip_before_battle(self):
        skip_action = next(
            action for action in self.actions if action.get("name") == "跳过战斗"
        )
        battle_action = next(
            action for action in self.actions if action.get("name") == "出战"
        )
        currency = object.__new__(SimulatedCurrency)
        StateKernel.__init__(currency)
        currency.state = "currency_main"
        currency.get_screen = Mock(return_value=255)
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = [
            {
                "raw_text": "跳过(2/2)",
                "box": [1749, 734, 1883, 767],
            }
        ]
        currency.do_action = Mock(return_value=1)
        currency._on_static_action_completed = Mock()

        result = currency.run_static(
            json_file={
                "跳过战斗": [skip_action],
                "出战": [battle_action],
            }
        )

        self.assertEqual(result, ("跳过战斗", 1))
        currency.ts.find_with_box.assert_called_once_with(
            [1600, 700, 1920, 790],
            redundancy=60,
        )
        currency.do_action.assert_called_once_with({"position": [1818, 750]})

    def test_blank_prompt_is_one_action_covering_every_screen(self):
        """「点击空白处继续」在开局前/首领前/奇遇都会出现，位置不同，必须一条动作全罩住。"""
        actions = [a for a in self.actions if a.get("name") == "点击空白继续"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(
            [a for a in self.actions if a.get("name", "").startswith("点击空白")],
            actions,
        )
        action = actions[0]
        self.assertEqual(action["trigger"]["text"], "点击空白处继续")
        self.assertEqual(action["actions"], ["click_blank_prompt"])
        top, bottom = action["trigger"]["box"][1], action["trigger"]["box"][3]
        for low, high in ((689, 718), (746, 746), (778, 807), (948, 975)):
            self.assertLessEqual(top, low)
            self.assertGreaterEqual(bottom, high)


    def test_tea_break_actions_cover_the_whole_flow(self):
        """幕后茶歇要走的六步：入口、聊一聊、推进对话、选项、确认、领奖。"""
        by_name = {a["name"]: a for a in self.actions}
        expected = {
            "进入幕后茶歇": ("幕后茶歇", [{"position": [1816, 752]}]),
            "茶歇-聊一聊": ("聊一聊", [{"position": [387, 837]}]),
            "茶歇-推进对话": ("点击空白处继续", [{"position": [1491, 920]}]),
            "茶歇-选择选项": ("返回", ["choose_tea_break_option"]),
            # 确认按钮纵向跟着被选中那一行走（实测 460~703 都可能），
            # 所以只锁右侧竖带，不锁高度
            "茶歇-确认奖励": ("确认", [{"text": "确认", "box": [1600, 400, 1900, 820]}]),
            "茶歇-领取奖励": ("领取茶歇奖励", [{"position": [961, 983]}]),
        }
        for name, (text, actions) in expected.items():
            with self.subTest(action=name):
                self.assertIn(name, by_name)
                self.assertEqual(by_name[name]["trigger"]["text"], text)
                self.assertEqual(by_name[name]["actions"], actions)

    def test_popup_triggers_survive_dropped_digits(self):
        """弹窗触发词不能带数字。

        OCR 会把数字整个吞掉（「请选择2名共舞的角色」→「请选择名共舞的角色」），
        触发词只要是不含数字的片段，带与不带数字两种识别结果都能命中。
        """
        popup_prefixes = ("银狼骇入效果", "克拉拉强化", "龙丹羁绊", "关闭黑市主理人",
                          "巡海游侠", "奇兽花园", "梦境交织")
        checked = 0
        for action in self.actions:
            if not action["name"].startswith(popup_prefixes):
                continue
            text = action["trigger"].get("text")
            self.assertIsNotNone(text, action["name"])
            self.assertNotRegex(text, r"\d", action["name"])
            checked += 1
        self.assertGreaterEqual(checked, 10)


if __name__ == "__main__":
    unittest.main()
