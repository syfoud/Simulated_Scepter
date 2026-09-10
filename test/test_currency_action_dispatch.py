import unittest
from unittest.mock import Mock, call, patch

from currency import SimulatedCurrency


class CurrencyActionDispatchTests(unittest.TestCase):
    triggers = (
        {"text": "\u51c6\u5907", "box": [0, 10, 0, 10], "redundancy": 20},
        {"photo": "icon", "pos": {"x": 10, "y": 20}, "threshold": 0.8},
        {"photo": "icon", "threshold": 0.8},
    )

    @staticmethod
    def make_currency(trigger):
        currency = object.__new__(SimulatedCurrency)
        currency.state = "ready"
        currency.get_screen = Mock(return_value=255)
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = [
            {"raw_text": "\u51c6\u5907", "box": [0, 10, 0, 10]}
        ]
        currency.check = Mock(return_value=True)
        currency.click_target = Mock(return_value=True)
        currency.action_history = []
        currency.action_time = 0
        currency.do_action = Mock()
        currency._on_static_action_completed = Mock()
        currency.default_json = {
            "group": [{"name": "choice", "trigger": trigger, "actions": ["first", "last"]}]
        }
        return currency

    @patch("currency.find_image_by_name", return_value="image")
    @patch("currency.time.time", return_value=100)
    def test_dispatch_contract(self, _time, _image):
        for trigger in self.triggers:
            for last_result in (None, 0, 1):
                with self.subTest(trigger=trigger, last_result=last_result):
                    currency = self.make_currency(trigger)
                    currency.action_history = [f"old-{i}" for i in range(10)]
                    currency.do_action.side_effect = [1, last_result]
                    sequence = Mock()
                    sequence.attach_mock(currency.do_action, "action")
                    sequence.attach_mock(currency._on_static_action_completed, "completed")

                    result = currency.run_static()

                    expected = 1 if "text" in trigger else (last_result or 0)
                    self.assertEqual(result, ("choice", expected))
                    self.assertEqual(
                        sequence.mock_calls,
                        [call.action("first"), call.action("last"), call.completed("choice")],
                    )
                    self.assertEqual(
                        currency.action_history, [f"old-{i}" for i in range(1, 10)] + ["choice"]
                    )
                    self.assertEqual(currency.action_time, 100)
                    if "text" in trigger:
                        currency.ts.find_with_box.assert_called_once_with(
                            trigger["box"], redundancy=20
                        )
                        currency.check.assert_not_called()
                        currency.click_target.assert_not_called()
                    elif "pos" in trigger:
                        currency.check.assert_called_once_with(
                            "icon", 10, 20, mask=None, threshold=0.8, use_binary=False
                        )
                        currency.click_target.assert_not_called()
                    else:
                        currency.click_target.assert_called_once_with(
                            "image", threshold=0.8, flag=False, click=False
                        )
                        currency.check.assert_not_called()

    @patch("currency.find_image_by_name", return_value="image")
    @patch("currency.time.time", return_value=100)
    def test_cooldown_noop(self, _time, _image):
        for trigger in self.triggers:
            with self.subTest(trigger=trigger):
                currency = self.make_currency({**trigger, "interval": 10})
                currency.action_history = ["choice"]
                currency.action_time = 95

                self.assertEqual(currency.run_static(), ("choice", 1))

                currency.do_action.assert_not_called()
                currency._on_static_action_completed.assert_not_called()
                self.assertEqual(currency.action_history, ["choice"])
                self.assertEqual(currency.action_time, 95)

    @patch("currency.find_image_by_name", return_value="image")
    def test_unmatched_trigger(self, _image):
        for trigger in self.triggers:
            for wrong_state in (False, True):
                with self.subTest(trigger=trigger, wrong_state=wrong_state):
                    currency = self.make_currency({**trigger, "condition": "ready"})
                    if wrong_state:
                        currency.state = "other"
                    else:
                        currency.ts.find_with_box.return_value = []
                        currency.check.return_value = False
                        currency.click_target.return_value = False

                    self.assertEqual(currency.run_static(), ("", 0))

                    currency.do_action.assert_not_called()
                    currency._on_static_action_completed.assert_not_called()
                    self.assertEqual(currency.action_history, [])

    def test_group_filter(self):
        currency = self.make_currency(self.triggers[0])
        currency.default_json["selected"] = [
            {"name": "selected", "trigger": self.triggers[0], "actions": ["selected"]},
            {"name": "later", "trigger": self.triggers[0], "actions": ["later"]},
        ]

        self.assertEqual(currency.run_static(action_list=["selected"]), ("selected", 1))

        currency.do_action.assert_called_once_with("selected")
        currency._on_static_action_completed.assert_called_once_with("selected")

    def test_failed_action(self):
        currency = self.make_currency(self.triggers[0])
        currency.do_action.side_effect = RuntimeError("input failed")

        with self.assertRaisesRegex(RuntimeError, "input failed"):
            currency.run_static()

        currency._on_static_action_completed.assert_not_called()
        self.assertEqual(currency.action_history, [])
        self.assertEqual(currency.action_time, 0)


if __name__ == "__main__":
    unittest.main()
