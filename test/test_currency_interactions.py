import unittest
from collections import Counter
from unittest.mock import MagicMock, Mock, call, patch

from core.currency.automation import SimulatedCurrency


class CurrencyInteractionTests(unittest.TestCase):
    @staticmethod
    def make_currency():
        currency = object.__new__(SimulatedCurrency)
        currency.prior_envir = []
        currency.envir = [[], [], [], []]
        currency.has_fresh = False
        currency.envir_seen = set()
        currency.gather_mode = False
        currency.ts = Mock()
        currency.get_screen = Mock(return_value=object())
        currency.ENVIR_BOXES = [
            [266, 375, 610, 413],
            [780, 375, 1134, 414],
            [1314, 373, 1645, 413],
        ]
        currency.BLESS_BOXES = [
            [298, 472, 608, 513],
            [783, 472, 1095, 513],
            [1298, 472, 1605, 513],
        ]
        return currency

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_fallback_uses_first_and_last_priority_groups(self, manager, _sleep):
        for groups in [[["一级"], [], [], ["四级"]], [[], [], [], ["一级"]]]:
            with self.subTest(groups=groups):
                currency = self.make_currency()
                currency.envir = groups
                currency.recognize_options = Mock(return_value=["一级", "四级", "其他"])
                currency._confirm_environment_selection = Mock(return_value=True)
                currency.investment_tracker = Mock()
                currency.update_state = Mock()
                manager.reset_mock()

                # 第一帧：没刷出必选 → 点一次刷新就返回，不改状态、不选卡。
                # 刷新按钮是 1920x1080 像素坐标，内核用 click_point 原样传出。
                self.assertIsNone(currency.select_envir())
                self.assertTrue(currency.has_fresh)
                self.assertEqual(manager.click_point.call_args, call(672, 984))
                currency.update_state.assert_not_called()

                # 第二帧：刷新过仍未命中必选 → 按优先级组兜底选卡。
                # 先点选中的环境（ENVIR_BOXES[0] 中心 438,394），再点确认按钮（1080,982），
                # 两次都走 click_point；选卡那一次会带上来源框，方便日志核对落点。
                self.assertEqual(currency.select_envir(), 1)
                self.assertIn(
                    call(438, 394, box=currency.ENVIR_BOXES[0]),
                    manager.click_point.call_args_list,
                )
                currency.update_state.assert_called_once_with("1-1")

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_blue_ocean_selects_unique_extra_environment_and_confirms(
        self, manager, _sleep
    ):
        currency = self.make_currency()
        currency.click_text = Mock(side_effect=lambda **kwargs: kwargs["text"] == "投资环境")
        currency.recognize_options = Mock(return_value=["", "唯一环境", ""])

        self.assertTrue(currency._select_blue_ocean_extra_environment())

        # 只点唯一那张卡（ENVIR_BOXES[1] 中心 957,394），再点确认按钮（1080,982）；
        # 坐标都是 1920x1080 像素，内核用 click_point 原样传出，并带上来源框。
        self.assertEqual(
            manager.mock_calls,
            [
                call.click_point(957, 394, box=currency.ENVIR_BOXES[1]),
                call.wait(),
                call.click_point(1080, 982, box=currency.ENVIRONMENT_CONFIRM_BOX),
                call.wait(),
            ],
        )
        currency.click_text.assert_called_once_with(
            text="投资环境",
            box=currency.ENVIRONMENT_TITLE_BOX,
            click=False,
            allow_fail=True,
        )

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_blue_ocean_does_not_reselect_three_option_screen(
        self, manager, _sleep
    ):
        currency = self.make_currency()
        currency.click_text = Mock(return_value=True)
        currency.recognize_options = Mock(return_value=["环境甲", "环境乙", "环境丙"])

        self.assertFalse(currency._select_blue_ocean_extra_environment(max_attempts=2))

        manager.click_point.assert_not_called()

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_blue_ocean_advances_state_only_after_extra_choice(
        self, _manager, _sleep
    ):
        currency = self.make_currency()
        currency.envir = [["蓝海"], [], [], []]
        currency.recognize_options = Mock(
            side_effect=[
                ["环境甲", "蓝海", "环境丙"],
                ["环境甲", "蓝海", "环境丙"],
            ]
        )
        currency._confirm_environment_selection = Mock(return_value=True)
        currency._select_blue_ocean_extra_environment = Mock(return_value=True)
        currency.investment_tracker = Mock()
        currency.update_state = Mock()

        # 第一帧只点刷新，第二帧才真正选中并处理蓝海额外环境
        self.assertIsNone(currency.select_envir())
        currency._select_blue_ocean_extra_environment.assert_not_called()
        self.assertEqual(currency.select_envir(), 1)

        currency._select_blue_ocean_extra_environment.assert_called_once_with()
        currency.investment_tracker.reset.assert_called_once_with()
        currency.update_state.assert_called_once_with("1-1")

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_blue_ocean_failure_does_not_advance_state(self, _manager, _sleep):
        currency = self.make_currency()
        currency.envir = [["蓝海"], [], [], []]
        currency.recognize_options = Mock(
            side_effect=[
                ["环境甲", "蓝海", "环境丙"],
                ["环境甲", "蓝海", "环境丙"],
            ]
        )
        currency._confirm_environment_selection = Mock(return_value=True)
        currency._select_blue_ocean_extra_environment = Mock(return_value=False)
        currency.investment_tracker = Mock()
        currency.update_state = Mock()

        self.assertIsNone(currency.select_envir())   # 第一帧点刷新
        self.assertEqual(currency.select_envir(), 0)  # 第二帧蓝海额外环境失败，不推进状态

        currency.investment_tracker.reset.assert_not_called()
        currency.update_state.assert_not_called()

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_refresh_retries_only_unchanged_middle_option(self, manager, _sleep):
        currency = self.make_currency()
        currency.recognize_options = Mock(
            side_effect=[
                ["新左", "旧中", "新右"],
                ["新左", "新中", "新右"],
            ]
        )

        result = currency._refresh_investment_options(["旧左", "旧中", "旧右"])

        self.assertEqual(result, ["新左", "新中", "新右"])
        # 三个刷新按钮的坐标来自 BLESS_REFRESH_POSITIONS（1920x1080 像素），
        # 第一轮三个都点，第二轮只重试文字没变的中间那个，故共 4 次 click_point。
        self.assertEqual(
            manager.click_point.call_args_list,
            [
                call(384, 869),
                call(868, 869),
                call(1380, 869),
                call(868, 869),
            ],
        )
        self.assertEqual(manager.wait.call_count, 4)

    @patch("core.currency.automation.key_mouse_manager")
    def test_blank_prompt_clicks_detected_text_and_exits_after_envir(self, manager):
        currency = object.__new__(SimulatedCurrency)
        currency.get_screen = Mock(return_value="frame")
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = [
            {"raw_text": "点击空白处继续", "box": [930, 690, 990, 718]}
        ]
        currency.click_box = Mock()
        currency.update_state = Mock()
        currency.state = "1-1"
        currency.gather_mode = True
        currency.envir_selected = False
        currency.exit_requested = False
        manager.reset_mock()

        # 环境还没选完（词缀后面那一次）：只点空白，不退出
        self.assertEqual(currency.click_blank_prompt(), 1)
        currency.click_box.assert_called_once_with([930, 690, 990, 718])
        self.assertFalse(currency.exit_requested)

        # 选完环境之后（奇遇这一次）：点完就请求退出
        currency.click_box.reset_mock()
        currency.envir_selected = True
        self.assertEqual(currency.click_blank_prompt(), 1)
        currency.click_box.assert_called_once_with([930, 690, 990, 718])
        self.assertTrue(currency.exit_requested)
        currency.update_state.assert_called_once_with("exit")

    @patch("core.currency.automation.key_mouse_manager")
    def test_blank_prompt_does_nothing_when_text_missing(self, manager):
        currency = object.__new__(SimulatedCurrency)
        currency.get_screen = Mock(return_value="frame")
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = []
        currency.click_box = Mock()
        currency.gather_mode = True
        currency.envir_selected = True
        currency.exit_requested = False
        manager.reset_mock()

        self.assertEqual(currency.click_blank_prompt(), 1)
        currency.click_box.assert_not_called()
        self.assertFalse(currency.exit_requested)

    @staticmethod
    def _affix_currency(read_affixes):
        currency = object.__new__(SimulatedCurrency)
        currency.get_screen = Mock(return_value="frame")
        currency.read_affixes = read_affixes
        currency.affix_sampler = Mock()
        currency.affix_sampler.record.return_value = []
        currency.affix_sampler.run_index = 1
        currency.affix_targets = []
        currency.gather_mode = False
        currency.max_runs = 0
        currency.affix_incomplete_rounds = 0
        currency.affixes_recorded = False
        return currency

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_affix_waits_until_four_are_visible(self, manager, _sleep):
        """词缀从左往右渐显，认到一两条就点下一步会漏采。"""
        currency = self._affix_currency(Mock(side_effect=[
            ["侵蚀·第一位面强化"],
            ["侵蚀·第一位面强化", "冷冻冬眠"],
            ["侵蚀·第一位面强化", "冷冻冬眠", "紧急止血"],
            ["侵蚀·第一位面强化", "冷冻冬眠", "紧急止血", "战个痛快"],
        ]))
        manager.reset_mock()

        self.assertEqual(currency.read_affixes_and_continue(), 1)

        currency.affix_sampler.record.assert_called_once_with(
            ["侵蚀·第一位面强化", "冷冻冬眠", "紧急止血", "战个痛快"], [])
        manager.click_point.assert_called_once_with(*SimulatedCurrency.AFFIX_NEXT_POSITION)

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_affix_partial_result_is_retried_before_accepting(self, manager, _sleep):
        currency = self._affix_currency(Mock(return_value=["侵蚀·第一位面强化"]))
        manager.reset_mock()

        rounds = SimulatedCurrency.AFFIX_PARTIAL_RETRY_ROUNDS
        for _ in range(rounds - 1):
            self.assertEqual(currency.read_affixes_and_continue(), 1)
            manager.click_point.assert_not_called()
            currency.affix_sampler.record.assert_not_called()

        # 最后一轮放弃等待，按现有结果记一笔并继续
        self.assertEqual(currency.read_affixes_and_continue(), 1)
        currency.affix_sampler.record.assert_called_once_with(["侵蚀·第一位面强化"], [])
        manager.click_point.assert_called_once_with(*SimulatedCurrency.AFFIX_NEXT_POSITION)

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_affix_click_is_skipped_when_nothing_is_recognised(self, manager, _sleep):
        currency = self._affix_currency(Mock(return_value=[]))
        manager.reset_mock()

        self.assertEqual(currency.read_affixes_and_continue(), 1)

        currency.affix_sampler.record.assert_not_called()
        manager.click_point.assert_not_called()

    @patch("core.currency.automation.time.sleep")
    def test_environment_wait_retries_until_cards_are_rendered(self, _sleep):
        currency = object.__new__(SimulatedCurrency)
        currency.get_screen = Mock(return_value="frame")
        currency.recognize_options = Mock(
            side_effect=[["二手市场", "", ""], ["黄金时代", "尾彩", "轮岗"]])
        currency.ENVIR_BOXES = [[0, 0, 10, 10]]

        self.assertEqual(
            currency.wait_environments(), ["黄金时代", "尾彩", "轮岗"])

    @patch("core.currency.automation.time.sleep")
    def test_environment_wait_gives_up_after_attempts(self, _sleep):
        currency = object.__new__(SimulatedCurrency)
        currency.get_screen = Mock(return_value="frame")
        currency.recognize_options = Mock(return_value=["二手市场", "", ""])
        currency.ENVIR_BOXES = [[0, 0, 10, 10]]

        self.assertEqual(currency.wait_environments(), ["二手市场", "", ""])
        self.assertEqual(
            currency.recognize_options.call_count,
            SimulatedCurrency.ENVIR_WAIT_ATTEMPTS,
        )

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_gather_mode_waits_inline_for_curiosity_then_exits(self, manager, _sleep):
        """1-1 奖励屏比奇遇先出现，必须在动作里就地等，否则别的动作会绕过等待去开战。"""
        currency = object.__new__(SimulatedCurrency)
        currency.gather_mode = True
        currency.exit_requested = False
        currency._stop = False
        currency.update_state = Mock()
        currency.preparation = Mock()
        currency.get_screen = Mock(return_value="frame")
        currency.ts = Mock()
        currency.ts.find_with_box.side_effect = [
            [],
            [],
            [{"raw_text": "点击空白处继续", "box": [900, 700, 1000, 720]}],
        ]
        currency.click_box = Mock()
        manager.reset_mock()

        self.assertEqual(currency.handle_1_1_reward(), 1)

        currency.click_box.assert_called_once_with([900, 700, 1000, 720])
        self.assertTrue(currency.exit_requested)
        currency.update_state.assert_called_once_with("exit")
        currency.preparation.reset_members.assert_not_called()

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_gather_mode_exits_when_curiosity_never_shows(self, _manager, _sleep):
        currency = object.__new__(SimulatedCurrency)
        currency.gather_mode = True
        currency.exit_requested = False
        currency._stop = False
        currency.update_state = Mock()
        currency.preparation = Mock()
        currency.get_screen = Mock(return_value="frame")
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = []
        currency.click_box = Mock()

        self.assertEqual(currency.handle_1_1_reward(), 1)

        currency.click_box.assert_not_called()
        self.assertTrue(currency.exit_requested)
        currency.update_state.assert_called_once_with("exit")
        currency.preparation.reset_members.assert_not_called()

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_affixes_are_recorded_once_per_run(self, manager, _sleep):
        """词缀一局只出现一次，切界面时文字还挂着不该重复识别。"""
        currency = self._affix_currency(
            Mock(return_value=["侵蚀·第一位面强化", "冷冻冬眠", "紧急止血", "战个痛快"]))
        manager.reset_mock()

        currency.read_affixes_and_continue()
        currency.read_affixes_and_continue()

        currency.affix_sampler.record.assert_called_once()
        manager.click_point.assert_called_once_with(*SimulatedCurrency.AFFIX_NEXT_POSITION)

    def test_read_affixes_keeps_only_known_names(self):
        """词缀条只保留能对齐到 53 条已知名的结果：UI 文案、数字、乱码统统丢掉。"""
        currency = object.__new__(SimulatedCurrency)
        currency.screen = MagicMock()
        currency.ts = Mock()
        currency.ts.ts.ocr.return_value = [
            ([], ("点击空白处继续", 0.99)),
            ([], ("战个痛快", 0.99)),
            ([], ("敌人难度 89", 0.99)),
            ([], ("随便乱码", 0.99)),
        ]

        self.assertEqual(currency.read_affixes(), ["战个痛快"])

    def test_read_affixes_repairs_ocr_variants(self):
        """实测常把首字吃掉或多认一笔（「山榜样激励」「首强化」），要纠回规范名。"""
        currency = object.__new__(SimulatedCurrency)
        currency.screen = MagicMock()
        currency.ts = Mock()
        currency.ts.ts.ocr.return_value = [
            ([], ("山榜样激励", 0.95)),
            ([], ("首强化", 0.95)),
            ([], ("战个痛快", 0.95)),
        ]

        self.assertEqual(
            currency.read_affixes(), ["榜样激励", "首领强化", "战个痛快"])

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_single_environment_card_is_treated_as_extra_environment(self, _manager, _sleep):
        """环境只有三张卡或蓝海的单张卡，没有两张的情况。"""
        currency = self.make_currency()
        currency.recognize_options = Mock(return_value=["蓝海", "", ""])
        currency._select_blue_ocean_extra_environment = Mock(return_value=True)
        currency.investment_tracker = Mock()
        currency.update_state = Mock()

        self.assertEqual(currency.select_envir(), 1)

        currency._select_blue_ocean_extra_environment.assert_called_once_with()
        currency.investment_tracker.reset.assert_called_once_with()
        currency.update_state.assert_called_once_with("1-1")
        self.assertTrue(currency.envir_selected)


    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_select_protagonist_runs_full_panel_flow(self, manager, _sleep):
        """4.7 新 UI：点按钮 → 等面板 → 拖角色 → 选光环 → 确认。"""
        currency = object.__new__(SimulatedCurrency)
        currency.click_text = Mock(return_value=True)
        manager.reset_mock()

        self.assertEqual(currency.select_protagonist(), 1)

        calls = manager.mock_calls
        # 第一次点击是「选择主角」按钮（中心 1816,750）
        self.assertEqual(
            calls[0],
            call.click_point(1816, 750, box=SimulatedCurrency.PROTAGONIST_BUTTON_BOX),
        )
        # 拖拽第一个角色到主角位
        self.assertIn(call.drag_point(805, 612, 960, 445), calls)
        # 选右侧光环
        self.assertIn(call.click_point(1501, 502), calls)
        # 最后点确认（中心 968,953）
        self.assertEqual(
            calls[-2],
            call.click_point(968, 953, box=SimulatedCurrency.PROTAGONIST_CONFIRM_BOX),
        )

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_select_protagonist_gives_up_when_panel_never_shows(self, manager, _sleep):
        currency = object.__new__(SimulatedCurrency)
        currency.click_text = Mock(return_value=False)
        manager.reset_mock()

        self.assertEqual(currency.select_protagonist(), 0)

        manager.drag_point.assert_not_called()
        # 只点了「选择主角」按钮，没有后续动作
        self.assertEqual(manager.click_point.call_count, 1)

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_select_protagonist_confirms_aura_replacement(self, manager, _sleep):
        """一局两次主角面板，第二次角色已有光环会弹替换确认，直接点确认。"""
        currency = object.__new__(SimulatedCurrency)
        # 面板标题一定命中；替换提示按第二次的实际情况给 True
        currency.click_text = Mock(side_effect=[True, True])
        manager.reset_mock()

        self.assertEqual(currency.select_protagonist(), 1)

        calls = manager.mock_calls
        self.assertIn(call.click_point(1501, 502), calls)                      # 光环
        self.assertIn(call.click_point(1189, 671), calls)                      # 替换确认
        # 替换确认在光环之后、面板确认之前
        self.assertLess(calls.index(call.click_point(1501, 502)),
                        calls.index(call.click_point(1189, 671)))
        self.assertEqual(
            calls[-2],
            call.click_point(968, 953, box=SimulatedCurrency.PROTAGONIST_CONFIRM_BOX),
        )

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_select_protagonist_skips_replacement_when_no_dialog(self, manager, _sleep):
        """第一次选主角不会弹替换确认，别去点那个坐标。"""
        currency = object.__new__(SimulatedCurrency)
        currency.click_text = Mock(side_effect=[True, False])
        manager.reset_mock()

        self.assertEqual(currency.select_protagonist(), 1)

        clicked = [c for c in manager.mock_calls if c[0] == "click_point"]
        self.assertNotIn(call.click_point(1189, 671), clicked)


    @patch("core.currency.automation.key_mouse_manager")
    def test_blank_prompt_clicks_the_detected_text_wherever_it_is(self, manager):
        currency = object.__new__(SimulatedCurrency)
        currency.get_screen = Mock(return_value="frame")
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = [
            {"raw_text": "点击空白处继续", "box": [908, 735, 1052, 760]},
        ]
        currency.click_box = Mock()
        manager.reset_mock()

        self.assertEqual(currency.click_blank_prompt(), 1)

        currency.click_box.assert_called_once_with([908, 735, 1052, 760])
        currency.ts.find_with_box.assert_called_once_with(SimulatedCurrency.BLANK_PROMPT_BOX)

if __name__ == "__main__":
    unittest.main()