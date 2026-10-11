"""隔离截图与输入，验证共用状态机和自由脚本清理路径。"""

import unittest
from unittest.mock import Mock, patch

from core.common.engine import StateKernel
from tool.action_script import run_script


class StateKernelTests(unittest.TestCase):
    def setUp(self):
        self.kernel = StateKernel()
        self.kernel.get_screen = Mock(return_value=255)
        self.kernel.ts = Mock()
        self.kernel.ts.find_with_box.return_value = [{"raw_text": "确认", "box": [0, 1, 0, 1]}]
        self.kernel.check = Mock(return_value=True)
        self.kernel.click_target = Mock(return_value=True)
        self.kernel.click_box = Mock()

    def actions(self, **trigger):
        return {"界面": [{"name": "确认窗口", "trigger": trigger,
                         "actions": [{"set_state": "done"}]}]}

    def test_state_transition_keeps_previous_state_and_same_state_keeps_time(self):
        with patch("core.common.engine.time.time", side_effect=[10, 20]), patch("core.common.engine.CUS_LOGGER"):
            self.kernel.update_state("run")
            self.kernel.update_state("run")
            self.assertEqual(self.kernel.last_update_time, 10)
            self.kernel.update_state("battle")
        self.assertEqual((self.kernel.state, self.kernel.last_state), ("battle", "run"))
        self.assertEqual(self.kernel.last_update_time, 20)

    def test_text_and_image_triggers_update_state_and_keep_result_contract(self):
        for trigger in ({"text": "确认", "box": [0, 1, 0, 1]},
                        {"photo": "button", "pos": {"x": 1, "y": 2}},
                        {"state_only": True, "condition": "done"}):
            with self.subTest(trigger=trigger):
                self.assertEqual(self.kernel.run_static(json_file=self.actions(**trigger)), ("确认窗口", 1))
                self.assertEqual(self.kernel.state, "done")

    def test_wrong_state_and_unmatched_screen_do_not_execute_actions(self):
        actions = self.actions(text="确认", box=[0, 1, 0, 1], condition="battle")
        self.assertEqual(self.kernel.run_static(json_file=actions), ("", 0))
        self.assertIsNone(self.kernel.state)
        self.kernel.ts.find_with_box.return_value = []
        self.assertEqual(self.kernel.run_static(json_file=self.actions(text="确认", box=[0, 1, 0, 1])), ("", 0))

    def test_once_event_rearms_only_after_trigger_disappears(self):
        actions = self.actions(text="确认", box=[0, 1, 0, 1], once=True)
        self.assertEqual(self.kernel.run_static(json_file=actions), ("确认窗口", 1))
        self.assertEqual(self.kernel.run_static(json_file=actions), ("", 0))
        self.kernel.ts.find_with_box.return_value = []
        self.assertEqual(self.kernel.run_static(json_file=actions), ("", 0))
        self.kernel.ts.find_with_box.return_value = [{"raw_text": "确认", "box": [0, 1, 0, 1]}]
        self.assertEqual(self.kernel.run_static(json_file=actions), ("确认窗口", 1))

    def test_interval_blocks_duplicate_actions_and_history_is_limited(self):
        self.kernel.action_history = ["old"] * 10
        self.kernel.do_action = Mock(return_value=7)
        actions = self.actions(photo="button", pos={"x": 1, "y": 2}, interval=10)
        with patch("core.common.engine.time.time", return_value=100):
            self.assertEqual(self.kernel.run_static(json_file=actions), ("确认窗口", 7))
            self.assertEqual(self.kernel.run_static(json_file=actions), ("确认窗口", 1))
        self.kernel.do_action.assert_called_once()
        self.assertEqual(len(self.kernel.action_history), 10)

    def test_black_screen_restores_state_when_loading_finishes(self):
        self.kernel.update_state("battle")
        self.kernel.get_screen.side_effect = [0, 255, 255]
        self.kernel.wait_loading()
        self.assertEqual(self.kernel.state, "battle")

    def test_initial_loading_returns_to_unknown_state_without_invalid_signal(self):
        self.kernel.get_screen.side_effect = [0, 255, 255]
        self.kernel.wait_loading()
        self.assertIsNone(self.kernel.state)

    def test_script_stops_and_releases_resources_on_success_or_failure(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                engine = Mock(_stop=False)

                def step():
                    if failure:
                        raise RuntimeError("识别失败")
                    self.assertEqual(engine.default_json, {"动作": []})
                    self.assertEqual(engine.default_json_path, "script.json")

                engine.start.side_effect = step
                with patch("tool.action_script.load_actions", return_value={"动作": []}), \
                        patch("tool.action_script.get_global_stop_flag", return_value=False):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, "识别失败"):
                            run_script(engine, "script.json")
                        engine.stop.assert_called_once()
                    else:
                        run_script(engine, "script.json")
                        engine.stop.assert_called_once()
                    engine.start.assert_called_once()
                    engine.prepare_script.assert_not_called()
                    engine.run_static.assert_not_called()

    def test_script_initialization_failure_still_releases_resources(self):
        engine = Mock(_stop=False)
        engine.start.side_effect = OSError("输入资源初始化失败")
        with patch("tool.action_script.load_actions", return_value={"动作": []}), \
                patch("tool.action_script.get_global_stop_flag", return_value=False):
            with self.assertRaises(OSError):
                run_script(engine, "script.json")
        engine.stop.assert_called_once()

    def test_cancelled_script_does_not_start_or_reset_stop_request(self):
        engine = Mock(_stop=True)
        with patch("tool.action_script.load_actions", return_value={"动作": []}), \
                patch("tool.action_script.get_global_stop_flag", return_value=True):
            run_script(engine, "script.json")
        engine.start.assert_not_called()
        self.assertTrue(engine._stop)

    def test_script_load_failure_releases_initialized_engine_without_starting(self):
        for result, error in ((None, OSError("读取失败")), ({}, None)):
            with self.subTest(result=result, error=error):
                engine = Mock(_stop=False)
                with patch("tool.action_script.load_actions", return_value=result, side_effect=error):
                    with self.assertRaises((OSError, ValueError)):
                        run_script(engine, "script.json")
                engine.start.assert_not_called()
                engine.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
