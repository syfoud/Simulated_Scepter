import unittest
from unittest.mock import Mock, patch

from core.currency.automation import SimulatedCurrency


class CurrencyDifficultySelectionTest(unittest.TestCase):
    @staticmethod
    def make_currency(state="difficulty_select"):
        currency = object.__new__(SimulatedCurrency)
        currency.state = state
        currency._stop = False
        currency.set_exit_plane = 2
        currency.exit_plane = 1
        currency.prior_environment_found = True
        currency.exit_requested = True
        currency.exit_started = True
        currency.run_history = Mock()
        currency.update_state = Mock(
            side_effect=lambda next_state: setattr(currency, "state", next_state)
        )
        return currency

    def test_default_step_limit_covers_highest_enemy_difficulty(self):
        self.assertGreaterEqual(SimulatedCurrency.DIFFICULTY_MAX_STEPS, 99)

    def test_lowest_difficulty_uses_selected_effect_region(self):
        currency = self.make_currency()
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = [
            {
                "raw_text": "开局时获得【精密拆装扳手】",
                "box": [747, 1060, 378, 409],
            }
        ]

        self.assertTrue(currency.is_one())

        currency.ts.find_with_box.assert_called_once_with(
            currency.DIFFICULTY_SELECTED_EFFECT_BOX,
            forward=1,
        )

    @patch("core.currency.automation.key_mouse_manager")
    def test_complete_selection_resets_per_run_flags(self, manager):
        """开局点击后重置本局标志；has_fresh 漏重置会吃掉下一局的刷新额度。

        状态不在这里推进：投资环境选择结束时由 select_envir 置为 1-1。
        """
        currency = self.make_currency()
        currency.has_fresh = True  # 上一局刷过刷新、并因此刷出了必选环境

        self.assertTrue(currency.complete_difficulty_selection())

        manager.clean.assert_called_once_with()
        # 「开始对局」按钮的 1920x1080 像素坐标，内核用 click_point 原样传出。
        manager.click_point.assert_called_once_with(1692, 965, force=True)
        manager.wait.assert_called_once_with()
        self.assertEqual(currency.exit_plane, 2)
        self.assertFalse(currency.prior_environment_found)
        self.assertFalse(currency.exit_requested)
        self.assertFalse(currency.exit_started)
        self.assertFalse(currency.has_fresh)
        currency.run_history.start_run.assert_called_once_with()
        currency.update_state.assert_not_called()

    @patch("core.currency.automation.key_mouse_manager")
    def test_complete_selection_is_idempotent_after_state_advanced(self, manager):
        currency = self.make_currency("currency_main")

        self.assertTrue(currency.complete_difficulty_selection())

        manager.clean.assert_not_called()
        manager.click_point.assert_not_called()
        currency.update_state.assert_not_called()
        currency.run_history.start_run.assert_not_called()

    @patch("core.currency.automation.key_mouse_manager")
    def test_scroll_loop_stops_when_state_already_advanced(self, manager):
        currency = self.make_currency("currency_main")
        currency.get_screen = Mock()
        currency.is_one = Mock()

        self.assertTrue(currency.select_difficulty_start())

        currency.get_screen.assert_not_called()
        currency.is_one.assert_not_called()
        manager.click_point.assert_not_called()

    @patch("core.currency.automation.key_mouse_manager")
    def test_detected_selection_uses_shared_completion_path(self, manager):
        currency = self.make_currency()
        currency.get_screen = Mock()
        currency.is_one = Mock(return_value=True)
        currency.complete_difficulty_selection = Mock(return_value=True)

        self.assertTrue(currency.select_difficulty_start())

        manager.clean.assert_called_once_with()
        currency.complete_difficulty_selection.assert_called_once_with()
        manager.click_point.assert_not_called()

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_each_step_finishes_before_next_ocr_check(self, manager, sleep):
        currency = self.make_currency()
        currency.get_screen = Mock()
        currency.is_one = Mock(side_effect=[False, True])
        currency.complete_difficulty_selection = Mock(return_value=True)

        self.assertTrue(currency.select_difficulty_start())

        manager.clean.assert_called_once_with()
        self.assertEqual(currency.get_screen.call_count, 2)  # 每次向下选择前都重新截图
        # 向下选择按钮的坐标来自 DIFFICULTY_DOWN_POSITION 常量（1920x1080 像素），原样传给 click_point。
        manager.click_point.assert_called_once_with(*currency.DIFFICULTY_DOWN_POSITION)
        manager.wait.assert_called_once_with()
        sleep.assert_not_called()  # 固定等待已删，改为等主循环下一帧重新识别

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_step_selection_stops_at_hard_limit(self, manager, _sleep):
        currency = self.make_currency()
        currency.DIFFICULTY_MAX_STEPS = 2
        currency.get_screen = Mock()
        currency.is_one = Mock(return_value=False)

        self.assertFalse(currency.select_difficulty_start())

        manager.clean.assert_called_once_with()
        self.assertEqual(manager.click_point.call_count, 2)
        manager.click_point.assert_called_with(*currency.DIFFICULTY_DOWN_POSITION)
        self.assertEqual(manager.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
