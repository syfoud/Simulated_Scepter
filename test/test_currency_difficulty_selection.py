import unittest
from unittest.mock import Mock, patch

from core.currency.automation import SimulatedCurrency


class CurrencyDifficultySelectionTest(unittest.TestCase):
    @staticmethod
    def make_currency(state="difficulty_select"):
        currency = object.__new__(SimulatedCurrency)
        currency.state = state
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
    def test_complete_selection_clears_drag_queue_and_updates_state(self, manager):
        currency = self.make_currency()

        self.assertTrue(currency.complete_difficulty_selection())

        manager.clean.assert_called_once_with()
        manager.click.assert_called_once_with(1692, 965, force=True)
        manager.wait.assert_called_once_with()
        currency.update_state.assert_called_once_with("startbattle")
        self.assertEqual(currency.state, "startbattle")

    @patch("core.currency.automation.key_mouse_manager")
    def test_complete_selection_is_idempotent_after_state_advanced(self, manager):
        currency = self.make_currency("startbattle")

        self.assertTrue(currency.complete_difficulty_selection())

        manager.clean.assert_not_called()
        manager.click.assert_not_called()
        currency.update_state.assert_not_called()

    @patch("core.currency.automation.key_mouse_manager")
    def test_scroll_loop_stops_when_state_already_advanced(self, manager):
        currency = self.make_currency("startbattle")
        currency.get_screen = Mock()
        currency.is_one = Mock()

        self.assertTrue(currency.select_difficulty_start())

        currency.get_screen.assert_not_called()
        currency.is_one.assert_not_called()
        manager.click.assert_not_called()

    @patch("core.currency.automation.key_mouse_manager")
    def test_detected_selection_uses_shared_completion_path(self, manager):
        currency = self.make_currency()
        currency.get_screen = Mock()
        currency.is_one = Mock(return_value=True)
        currency.complete_difficulty_selection = Mock(return_value=True)

        self.assertTrue(currency.select_difficulty_start())

        manager.clean.assert_called_once_with()
        currency.complete_difficulty_selection.assert_called_once_with()
        manager.click.assert_not_called()

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_each_step_finishes_before_next_ocr_check(self, manager, sleep):
        currency = self.make_currency()
        currency.get_screen = Mock()
        currency.is_one = Mock(side_effect=[False, True])
        currency.complete_difficulty_selection = Mock(return_value=True)

        self.assertTrue(currency.select_difficulty_start())

        manager.clean.assert_called_once_with()
        manager.click.assert_called_once_with(*currency.DIFFICULTY_DOWN_POSITION)
        manager.wait.assert_called_once_with()
        sleep.assert_called_once_with(currency.DIFFICULTY_SETTLE_SECONDS)

    @patch("core.currency.automation.time.sleep")
    @patch("core.currency.automation.key_mouse_manager")
    def test_step_selection_stops_at_hard_limit(self, manager, _sleep):
        currency = self.make_currency()
        currency.DIFFICULTY_MAX_STEPS = 2
        currency.get_screen = Mock()
        currency.is_one = Mock(return_value=False)

        self.assertFalse(currency.select_difficulty_start())

        manager.clean.assert_called_once_with()
        self.assertEqual(manager.click.call_count, 2)
        manager.click.assert_called_with(*currency.DIFFICULTY_DOWN_POSITION)
        self.assertEqual(manager.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
