import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from currency import SimulatedCurrency


class CurrencyInteractionTests(unittest.TestCase):
    @staticmethod
    def make_currency():
        currency = object.__new__(SimulatedCurrency)
        currency.ts = Mock()
        currency.get_screen = Mock(return_value=object())
        currency.ENVIR_BOXES = [
            [266, 610, 375, 413],
            [780, 1134, 375, 414],
            [1314, 1645, 373, 413],
        ]
        currency.BLESS_BOXES = [
            [298, 608, 472, 513],
            [783, 1095, 472, 513],
            [1298, 1605, 472, 513],
        ]
        return currency

    @patch("currency.time.sleep")
    @patch("currency.key_mouse_manager")
    def test_blue_ocean_selects_unique_extra_environment_and_confirms(
        self, manager, _sleep
    ):
        currency = self.make_currency()
        currency.click_text = Mock(side_effect=lambda **kwargs: kwargs["text"] == "投资环境")
        currency.recognize_options = Mock(return_value=["", "唯一环境", ""])

        self.assertTrue(currency._select_blue_ocean_extra_environment())

        self.assertEqual(
            manager.mock_calls,
            [call.click(957, 394), call.wait(), call.click(1080, 982), call.wait()],
        )
        currency.click_text.assert_called_once_with(
            text="投资环境",
            box=currency.ENVIRONMENT_TITLE_BOX,
            click=False,
            allow_fail=True,
        )

    @patch("currency.time.sleep")
    @patch("currency.key_mouse_manager")
    def test_blue_ocean_does_not_reselect_three_option_screen(
        self, manager, _sleep
    ):
        currency = self.make_currency()
        currency.click_text = Mock(return_value=True)
        currency.recognize_options = Mock(return_value=["环境甲", "环境乙", "环境丙"])

        self.assertFalse(currency._select_blue_ocean_extra_environment(max_attempts=2))

        manager.click.assert_not_called()

    @patch("currency.time.sleep")
    @patch("currency.key_mouse_manager")
    def test_blue_ocean_advances_state_only_after_extra_choice(
        self, _manager, _sleep
    ):
        currency = self.make_currency()
        currency.tk = SimpleNamespace(
            prior_envir=[],
            envir=[[], ["蓝海"], [], [], []],
        )
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

        self.assertEqual(currency.select_envir(), 1)

        currency._select_blue_ocean_extra_environment.assert_called_once_with()
        currency.investment_tracker.reset.assert_called_once_with()
        currency.update_state.assert_called_once_with("1-1")

    @patch("currency.time.sleep")
    @patch("currency.key_mouse_manager")
    def test_blue_ocean_failure_does_not_advance_state(self, _manager, _sleep):
        currency = self.make_currency()
        currency.tk = SimpleNamespace(
            prior_envir=[],
            envir=[[], ["蓝海"], [], [], []],
        )
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

        self.assertEqual(currency.select_envir(), 0)

        currency.investment_tracker.reset.assert_not_called()
        currency.update_state.assert_not_called()

    @patch("currency.time.sleep")
    @patch("currency.key_mouse_manager")
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
        self.assertEqual(
            manager.click.call_args_list,
            [
                call(384, 869),
                call(868, 869),
                call(1380, 869),
                call(868, 869),
            ],
        )
        self.assertEqual(manager.wait.call_count, 4)


if __name__ == "__main__":
    unittest.main()
